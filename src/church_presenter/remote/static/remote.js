(() => {
  "use strict";

  const canvas = document.querySelector("#screen");
  const context = canvas.getContext("2d", { alpha: false });
  const status = document.querySelector("#status");
  const zoomLevel = document.querySelector("#zoomLevel");
  const viewport = document.querySelector("#viewport");
  const keyboardCapture = document.querySelector("#keyboardCapture");
  const resetViewButton = document.querySelector("#resetView");

  const MIN_ZOOM = 1;
  const MAX_ZOOM = 4;
  const DOUBLE_TAP_ZOOM = 2;
  const DOUBLE_TAP_MS = 320;
  const DOUBLE_TAP_DISTANCE = 36;
  const PINCH_GRACE_MS = 100;
  const DRAG_THRESHOLD = 6;
  const SYNTHETIC_CLICK_BLOCK_MS = 700;
  const MOBILE_MAX_RENDER_WIDTH = 1024;

  let socket;
  let pendingMetadata = null;
  let queuedFrame = null;
  let renderingFrame = false;
  let bitmapResizeSupported = true;
  let droppedFrames = 0;
  let renderedSequence = 0;
  let retryDelay = 500;
  let resizeFrame = 0;
  let syntheticClickBlockedUntil = 0;
  let lastTap = null;
  let singleTouch = null;
  let gestureMode = "idle";
  let pinch = null;

  const activeTouches = new Map();
  const prefersReducedCanvas =
    window.matchMedia?.("(pointer: coarse)").matches ?? false;
  const frameSize = {
    width: canvas.width || 1600,
    height: canvas.height || 900,
  };
  const layoutSize = {
    width: 0,
    height: 0,
  };
  const view = {
    zoom: MIN_ZOOM,
    fitScale: 1,
    panX: 0,
    panY: 0,
    left: 0,
    top: 0,
    scale: 1,
  };

  const clamp = (value, minimum, maximum) =>
    Math.max(minimum, Math.min(maximum, value));

  const setStatus = (text, ok = false) => {
    status.textContent = text;
    status.style.color = ok ? "#9fdaaf" : "#f0bd72";
  };

  const modifiers = (event) => [
    event.altKey && "alt",
    event.ctrlKey && "control",
    event.metaKey && "meta",
    event.shiftKey && "shift",
  ].filter(Boolean);

  const send = (message) => {
    if (socket?.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify(message));
    }
  };

  const backingSizeFor = (width, height) => {
    const scale = prefersReducedCanvas
      ? Math.min(1, MOBILE_MAX_RENDER_WIDTH / width)
      : 1;
    return {
      width: Math.max(1, Math.round(width * scale)),
      height: Math.max(1, Math.round(height * scale)),
    };
  };

  const viewportPoint = (clientX, clientY) => {
    const rect = viewport.getBoundingClientRect();
    return {
      x: clientX - rect.left,
      y: clientY - rect.top,
    };
  };

  const geometryFor = (zoom = view.zoom) => {
    const width = viewport.clientWidth;
    const height = viewport.clientHeight;
    const scale = view.fitScale * zoom;
    const scaledWidth = frameSize.width * scale;
    const scaledHeight = frameSize.height * scale;
    return {
      width,
      height,
      scale,
      scaledWidth,
      scaledHeight,
      centeredLeft: (width - scaledWidth) / 2,
      centeredTop: (height - scaledHeight) / 2,
      maxPanX: Math.max(0, (scaledWidth - width) / 2),
      maxPanY: Math.max(0, (scaledHeight - height) / 2),
    };
  };

  const applyView = () => {
    const geometry = geometryFor();
    view.panX = clamp(view.panX, -geometry.maxPanX, geometry.maxPanX);
    view.panY = clamp(view.panY, -geometry.maxPanY, geometry.maxPanY);
    view.scale = geometry.scale;
    view.left = geometry.centeredLeft + view.panX;
    view.top = geometry.centeredTop + view.panY;
    canvas.style.transform =
      `translate3d(${view.left}px, ${view.top}px, 0) scale(${view.scale})`;
    canvas.dataset.zoom = view.zoom.toFixed(4);
    canvas.dataset.panX = view.panX.toFixed(2);
    canvas.dataset.panY = view.panY.toFixed(2);
    zoomLevel.textContent =
      view.zoom <= MIN_ZOOM + 0.001 ? "맞춤" : `${view.zoom.toFixed(1)}×`;
  };

  const contentAtViewportPoint = (point) => ({
    x: (point.x - view.left) / view.scale,
    y: (point.y - view.top) / view.scale,
  });

  const normalizedPoint = (clientX, clientY) => {
    const content = contentAtViewportPoint(viewportPoint(clientX, clientY));
    return {
      x: clamp(content.x / frameSize.width, 0, 1),
      y: clamp(content.y / frameSize.height, 0, 1),
    };
  };

  const centerAnchor = () => {
    if (
      !view.scale ||
      !frameSize.width ||
      !frameSize.height ||
      !layoutSize.width ||
      !layoutSize.height
    ) {
      return { x: 0.5, y: 0.5 };
    }
    const content = contentAtViewportPoint({
      x: layoutSize.width / 2,
      y: layoutSize.height / 2,
    });
    return {
      x: clamp(content.x / frameSize.width, 0, 1),
      y: clamp(content.y / frameSize.height, 0, 1),
    };
  };

  const restoreCenterAnchor = (anchor) => {
    const geometry = geometryFor();
    const desiredLeft =
      geometry.width / 2 - anchor.x * frameSize.width * geometry.scale;
    const desiredTop =
      geometry.height / 2 - anchor.y * frameSize.height * geometry.scale;
    view.panX = desiredLeft - geometry.centeredLeft;
    view.panY = desiredTop - geometry.centeredTop;
    applyView();
  };

  const updateLayout = (preserveCenter = true) => {
    if (!viewport.clientWidth || !viewport.clientHeight) return;
    const anchor = preserveCenter ? centerAnchor() : { x: 0.5, y: 0.5 };
    view.fitScale = Math.min(
      viewport.clientWidth / frameSize.width,
      viewport.clientHeight / frameSize.height,
    );
    layoutSize.width = viewport.clientWidth;
    layoutSize.height = viewport.clientHeight;
    canvas.style.width = `${frameSize.width}px`;
    canvas.style.height = `${frameSize.height}px`;
    if (view.zoom <= MIN_ZOOM + 0.001) {
      view.zoom = MIN_ZOOM;
      view.panX = 0;
      view.panY = 0;
      applyView();
    } else {
      restoreCenterAnchor(anchor);
    }
  };

  const scheduleLayout = () => {
    window.cancelAnimationFrame(resizeFrame);
    resizeFrame = window.requestAnimationFrame(() => updateLayout(true));
  };

  const resetView = () => {
    view.zoom = MIN_ZOOM;
    view.panX = 0;
    view.panY = 0;
    applyView();
  };

  const setZoomAt = (zoom, clientX, clientY) => {
    const nextZoom = clamp(zoom, MIN_ZOOM, MAX_ZOOM);
    const point = viewportPoint(clientX, clientY);
    const content = contentAtViewportPoint(point);
    view.zoom = nextZoom;
    const geometry = geometryFor();
    view.panX = point.x - content.x * geometry.scale - geometry.centeredLeft;
    view.panY = point.y - content.y * geometry.scale - geometry.centeredTop;
    applyView();
  };

  const toggleDoubleTapZoom = (clientX, clientY) => {
    if (view.zoom > MIN_ZOOM + 0.001) {
      resetView();
    } else {
      setZoomAt(DOUBLE_TAP_ZOOM, clientX, clientY);
    }
  };

  const sendPointer = (action, clientX, clientY, button, event) => {
    send({
      type: "pointer",
      action,
      ...normalizedPoint(clientX, clientY),
      button,
      modifiers: modifiers(event),
    });
  };

  const buttonName = (button) => ["left", "middle", "right"][button] || "none";
  const distance = (first, second) =>
    Math.hypot(second.x - first.x, second.y - first.y);
  const midpoint = (first, second) => ({
    x: (first.x + second.x) / 2,
    y: (first.y + second.y) / 2,
  });

  const clearSingleTimer = () => {
    if (singleTouch?.timer) {
      window.clearTimeout(singleTouch.timer);
      singleTouch.timer = 0;
    }
  };

  const pressSingleTouch = (event) => {
    if (
      !singleTouch ||
      singleTouch.pressed ||
      singleTouch.suppressed ||
      activeTouches.size !== 1
    ) {
      return;
    }
    sendPointer(
      "press",
      singleTouch.startX,
      singleTouch.startY,
      "left",
      event,
    );
    singleTouch.pressed = true;
  };

  const beginSingleTouch = (event) => {
    const now = performance.now();
    const isDoubleTap =
      lastTap &&
      now - lastTap.time <= DOUBLE_TAP_MS &&
      Math.hypot(event.clientX - lastTap.x, event.clientY - lastTap.y) <=
        DOUBLE_TAP_DISTANCE;
    singleTouch = {
      id: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      lastX: event.clientX,
      lastY: event.clientY,
      pressed: false,
      moved: false,
      suppressed: Boolean(isDoubleTap),
      timer: 0,
    };
    if (isDoubleTap) {
      gestureMode = "double-tap-candidate";
      return;
    }
    gestureMode = "single";
    singleTouch.timer = window.setTimeout(
      () => pressSingleTouch(event),
      PINCH_GRACE_MS,
    );
  };

  const cancelSingleForPinch = (event) => {
    clearSingleTimer();
    if (singleTouch?.pressed) {
      sendPointer(
        "release",
        singleTouch.lastX,
        singleTouch.lastY,
        "left",
        event,
      );
    }
    singleTouch = null;
  };

  const beginPinch = (event) => {
    cancelSingleForPinch(event);
    lastTap = null;
    const touches = [...activeTouches.values()].slice(0, 2);
    const middle = midpoint(touches[0], touches[1]);
    const localMiddle = viewportPoint(middle.x, middle.y);
    pinch = {
      startDistance: Math.max(1, distance(touches[0], touches[1])),
      startZoom: view.zoom,
      anchor: contentAtViewportPoint(localMiddle),
    };
    gestureMode = "pinch";
    syntheticClickBlockedUntil =
      performance.now() + SYNTHETIC_CLICK_BLOCK_MS;
  };

  const updatePinch = () => {
    if (!pinch || activeTouches.size < 2) return;
    const touches = [...activeTouches.values()].slice(0, 2);
    const middle = midpoint(touches[0], touches[1]);
    const localMiddle = viewportPoint(middle.x, middle.y);
    view.zoom = clamp(
      pinch.startZoom *
        (distance(touches[0], touches[1]) / pinch.startDistance),
      MIN_ZOOM,
      MAX_ZOOM,
    );
    const geometry = geometryFor();
    view.panX =
      localMiddle.x - pinch.anchor.x * geometry.scale - geometry.centeredLeft;
    view.panY =
      localMiddle.y - pinch.anchor.y * geometry.scale - geometry.centeredTop;
    applyView();
  };

  const touchPointerDown = (event) => {
    event.preventDefault();
    canvas.setPointerCapture(event.pointerId);
    activeTouches.set(event.pointerId, {
      x: event.clientX,
      y: event.clientY,
    });
    if (activeTouches.size === 1 && gestureMode === "idle") {
      beginSingleTouch(event);
    } else if (activeTouches.size === 2) {
      beginPinch(event);
    }
  };

  const touchPointerMove = (event) => {
    event.preventDefault();
    if (!activeTouches.has(event.pointerId)) return;
    activeTouches.set(event.pointerId, {
      x: event.clientX,
      y: event.clientY,
    });
    if (gestureMode === "pinch" || gestureMode === "pinch-ending") {
      updatePinch();
      return;
    }
    if (
      (gestureMode !== "single" &&
        gestureMode !== "double-tap-candidate") ||
      !singleTouch ||
      singleTouch.id !== event.pointerId
    ) {
      return;
    }
    singleTouch.lastX = event.clientX;
    singleTouch.lastY = event.clientY;
    const moved =
      Math.hypot(
        event.clientX - singleTouch.startX,
        event.clientY - singleTouch.startY,
      ) >= DRAG_THRESHOLD;
    if (
      moved &&
      singleTouch.suppressed &&
      gestureMode === "double-tap-candidate"
    ) {
      singleTouch.suppressed = false;
      lastTap = null;
      gestureMode = "single";
    }
    if (moved && !singleTouch.pressed) {
      clearSingleTimer();
      pressSingleTouch(event);
    }
    if (singleTouch.pressed) {
      singleTouch.moved ||= moved;
      sendPointer("move", event.clientX, event.clientY, "none", event);
    }
  };

  const finishTouchPointer = (event, cancelled = false) => {
    event.preventDefault();
    const wasPinch =
      gestureMode === "pinch" || gestureMode === "pinch-ending";
    activeTouches.delete(event.pointerId);
    if (wasPinch) {
      pinch = null;
      gestureMode = activeTouches.size ? "pinch-ending" : "idle";
      syntheticClickBlockedUntil =
        performance.now() + SYNTHETIC_CLICK_BLOCK_MS;
      return;
    }
    if (!singleTouch || singleTouch.id !== event.pointerId) {
      if (!activeTouches.size) gestureMode = "idle";
      return;
    }
    clearSingleTimer();
    const completedDoubleTap =
      singleTouch.suppressed && !singleTouch.moved && !cancelled;
    if (completedDoubleTap) {
      lastTap = null;
      syntheticClickBlockedUntil =
        performance.now() + SYNTHETIC_CLICK_BLOCK_MS;
      toggleDoubleTapZoom(event.clientX, event.clientY);
    } else if (!singleTouch.suppressed && !cancelled) {
      if (!singleTouch.pressed) {
        sendPointer("press", event.clientX, event.clientY, "left", event);
      }
      sendPointer("release", event.clientX, event.clientY, "left", event);
    } else if (singleTouch.pressed) {
      sendPointer("release", event.clientX, event.clientY, "left", event);
    }
    if (!cancelled && !singleTouch.suppressed && !singleTouch.moved) {
      lastTap = {
        time: performance.now(),
        x: event.clientX,
        y: event.clientY,
      };
    } else if (!singleTouch.suppressed) {
      lastTap = null;
    }
    singleTouch = null;
    gestureMode = activeTouches.size ? gestureMode : "idle";
  };

  canvas.addEventListener("pointerdown", (event) => {
    if (event.pointerType === "touch") {
      touchPointerDown(event);
      return;
    }
    event.preventDefault();
    canvas.setPointerCapture(event.pointerId);
    sendPointer(
      "press",
      event.clientX,
      event.clientY,
      buttonName(event.button),
      event,
    );
  });

  canvas.addEventListener("pointermove", (event) => {
    if (event.pointerType === "touch") {
      touchPointerMove(event);
      return;
    }
    if (!event.buttons) return;
    event.preventDefault();
    sendPointer("move", event.clientX, event.clientY, "none", event);
  });

  canvas.addEventListener("pointerup", (event) => {
    if (event.pointerType === "touch") {
      finishTouchPointer(event);
      return;
    }
    event.preventDefault();
    sendPointer(
      "release",
      event.clientX,
      event.clientY,
      buttonName(event.button),
      event,
    );
  });

  canvas.addEventListener("pointercancel", (event) => {
    if (event.pointerType === "touch") {
      finishTouchPointer(event, true);
    }
  });

  canvas.addEventListener("dblclick", (event) => {
    event.preventDefault();
    if (performance.now() < syntheticClickBlockedUntil) return;
    sendPointer(
      "double",
      event.clientX,
      event.clientY,
      buttonName(event.button),
      event,
    );
  });

  canvas.addEventListener("click", (event) => {
    if (performance.now() < syntheticClickBlockedUntil) {
      event.preventDefault();
      event.stopImmediatePropagation();
    }
  });

  canvas.addEventListener(
    "wheel",
    (event) => {
      event.preventDefault();
      send({
        type: "wheel",
        ...normalizedPoint(event.clientX, event.clientY),
        deltaX: event.deltaX,
        deltaY: event.deltaY,
        modifiers: modifiers(event),
      });
    },
    { passive: false },
  );
  canvas.addEventListener("contextmenu", (event) => event.preventDefault());

  const sendKey = (event, action) => {
    if (event.key === "Unidentified") return;
    event.preventDefault();
    send({
      type: "key",
      action,
      key: event.key,
      code: event.code || "",
      text: event.key.length === 1 ? event.key : "",
      modifiers: modifiers(event),
    });
  };

  window.addEventListener("keydown", (event) => {
    if (document.activeElement === keyboardCapture && event.key.length === 1) return;
    sendKey(event, "press");
  });
  window.addEventListener("keyup", (event) => {
    if (document.activeElement === keyboardCapture && event.key.length === 1) return;
    sendKey(event, "release");
  });
  keyboardCapture.addEventListener("keydown", (event) => {
    if (event.key.length !== 1) sendKey(event, "press");
  });
  keyboardCapture.addEventListener("keyup", (event) => {
    if (event.key.length !== 1) sendKey(event, "release");
  });
  keyboardCapture.addEventListener("input", () => {
    for (const character of keyboardCapture.value) {
      send({
        type: "key",
        action: "press",
        key: character,
        code: "",
        text: character,
        modifiers: [],
      });
      send({
        type: "key",
        action: "release",
        key: character,
        code: "",
        text: character,
        modifiers: [],
      });
    }
    keyboardCapture.value = "";
  });

  const setFrameSize = (width, height) => {
    const backing = backingSizeFor(width, height);
    if (
      width === frameSize.width &&
      height === frameSize.height &&
      canvas.width === backing.width &&
      canvas.height === backing.height
    ) {
      return;
    }
    const anchor = centerAnchor();
    frameSize.width = width;
    frameSize.height = height;
    canvas.width = backing.width;
    canvas.height = backing.height;
    canvas.style.width = `${width}px`;
    canvas.style.height = `${height}px`;
    view.fitScale = Math.min(
      viewport.clientWidth / frameSize.width,
      viewport.clientHeight / frameSize.height,
    );
    restoreCenterAnchor(anchor);
  };

  const loadImageElement = (blob) =>
    new Promise((resolve, reject) => {
      const url = URL.createObjectURL(blob);
      const image = new Image();
      image.decoding = "async";
      image.onload = () => {
        resolve({
          source: image,
          close: () => URL.revokeObjectURL(url),
        });
      };
      image.onerror = () => {
        URL.revokeObjectURL(url);
        reject(new Error("JPEG decode failed"));
      };
      image.src = url;
    });

  const decodedBitmap = (bitmap) => ({
    source: bitmap,
    close: () => bitmap.close(),
  });

  const decodeFrame = async (blob, backing) => {
    if (typeof createImageBitmap === "function") {
      if (prefersReducedCanvas && bitmapResizeSupported) {
        try {
          return decodedBitmap(
            await createImageBitmap(blob, {
              resizeWidth: backing.width,
              resizeHeight: backing.height,
              resizeQuality: "medium",
            }),
          );
        } catch {
          bitmapResizeSupported = false;
        }
      }
      return decodedBitmap(await createImageBitmap(blob));
    }
    return loadImageElement(blob);
  };

  const drawFrame = async (blob, metadata) => {
    const backing = backingSizeFor(metadata.width, metadata.height);
    const decoded = await decodeFrame(blob, backing);
    setFrameSize(metadata.width, metadata.height);
    try {
      context.drawImage(decoded.source, 0, 0, canvas.width, canvas.height);
    } finally {
      decoded.close();
    }
    renderedSequence = Math.max(
      renderedSequence,
      Number(metadata.sequence) || 0,
    );
  };

  const renderLatestFrames = async () => {
    if (renderingFrame) return;
    renderingFrame = true;
    try {
      while (queuedFrame) {
        const frame = queuedFrame;
        queuedFrame = null;
        try {
          await drawFrame(frame.blob, frame.metadata);
        } catch {
          setStatus("프레임 처리 오류");
        }
      }
    } finally {
      renderingFrame = false;
      if (queuedFrame) void renderLatestFrames();
    }
  };

  const enqueueFrame = (blob, metadata) => {
    if (queuedFrame) droppedFrames += 1;
    queuedFrame = { blob, metadata };
    void renderLatestFrames();
  };

  const connect = () => {
    const scheme = location.protocol === "https:" ? "wss:" : "ws:";
    socket = new WebSocket(`${scheme}//${location.host}/ws`);
    socket.binaryType = "blob";
    setStatus("연결 중…");
    socket.onopen = () => {
      retryDelay = 500;
      setStatus("연결됨", true);
    };
    socket.onmessage = (event) => {
      if (typeof event.data === "string") {
        try {
          pendingMetadata = JSON.parse(event.data);
        } catch {
          pendingMetadata = null;
        }
      } else if (pendingMetadata) {
        const metadata = pendingMetadata;
        pendingMetadata = null;
        enqueueFrame(event.data, metadata);
      }
    };
    socket.onclose = () => {
      setStatus("연결 끊김 · 재시도 중");
      window.setTimeout(connect, retryDelay);
      retryDelay = Math.min(8000, retryDelay * 1.7);
    };
    socket.onerror = () => socket.close();
  };

  resetViewButton.addEventListener("click", resetView);
  document.querySelector("#fullscreen").addEventListener("click", () => {
    if (document.fullscreenElement) {
      document.exitFullscreen();
    } else {
      document.documentElement.requestFullscreen();
    }
  });
  document
    .querySelector("#keyboard")
    .addEventListener("click", () => keyboardCapture.focus());

  window.addEventListener("resize", scheduleLayout);
  window.addEventListener("orientationchange", scheduleLayout);
  document.addEventListener("fullscreenchange", scheduleLayout);
  if ("ResizeObserver" in window) {
    new ResizeObserver(scheduleLayout).observe(viewport);
  }

  window.ChurchPresenterRemoteView = Object.freeze({
    getState: () => ({
      zoom: view.zoom,
      panX: view.panX,
      panY: view.panY,
      fitScale: view.fitScale,
      left: view.left,
      top: view.top,
      scale: view.scale,
      frameWidth: frameSize.width,
      frameHeight: frameSize.height,
      renderWidth: canvas.width,
      renderHeight: canvas.height,
      renderingFrame,
      queuedFrame: Boolean(queuedFrame),
      droppedFrames,
      renderedSequence,
      gestureMode,
    }),
    normalizedAt: (clientX, clientY) => normalizedPoint(clientX, clientY),
    reset: resetView,
  });

  updateLayout(false);
  connect();
})();
