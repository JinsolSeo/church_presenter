import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const sourcePath = process.argv[2];
if (!sourcePath) throw new Error("remote.js path is required");

const listeners = new Map();
const windowListeners = new Map();
const documentListeners = new Map();

const element = (properties = {}) => ({
  addEventListener(type, callback) {
    if (!this.listeners) this.listeners = new Map();
    this.listeners.set(type, callback);
  },
  listeners: new Map(),
  style: {},
  dataset: {},
  textContent: "",
  value: "",
  focus() {},
  ...properties,
});

const viewport = element({
  clientWidth: 400,
  clientHeight: 700,
  getBoundingClientRect() {
    return {
      left: 0,
      top: 50,
      width: this.clientWidth,
      height: this.clientHeight,
    };
  },
});
const canvas = element({
  width: 1600,
  height: 900,
  getContext() {
    return {
      drawImage(image) {
        drawnFrames.push(image.id);
      },
    };
  },
  setPointerCapture() {},
});
const status = element();
const zoomLevel = element();
const keyboardCapture = element();
const resetView = element();
const fullscreen = element();
const keyboard = element();
const elements = new Map([
  ["#screen", canvas],
  ["#status", status],
  ["#zoomLevel", zoomLevel],
  ["#viewport", viewport],
  ["#keyboardCapture", keyboardCapture],
  ["#resetView", resetView],
  ["#fullscreen", fullscreen],
  ["#keyboard", keyboard],
]);

globalThis.document = {
  activeElement: null,
  fullscreenElement: null,
  documentElement: {
    requestFullscreen() {},
  },
  querySelector(selector) {
    return elements.get(selector);
  },
  addEventListener(type, callback) {
    documentListeners.set(type, callback);
  },
  exitFullscreen() {},
};
globalThis.location = {
  protocol: "http:",
  host: "127.0.0.1:8765",
};
globalThis.window = {
  addEventListener(type, callback) {
    windowListeners.set(type, callback);
  },
  setTimeout,
  clearTimeout,
  requestAnimationFrame(callback) {
    callback();
    return 1;
  },
  cancelAnimationFrame() {},
  matchMedia() {
    return { matches: true };
  },
};
globalThis.ResizeObserver = class {
  observe() {}
};

const sent = [];
const drawnFrames = [];
let lastSocket;
globalThis.WebSocket = class {
  static OPEN = 1;

  constructor() {
    this.readyState = WebSocket.OPEN;
    lastSocket = this;
  }

  send(message) {
    sent.push(JSON.parse(message));
  }

  close() {}
};
globalThis.createImageBitmap = async () => ({
  id: "immediate",
  close() {},
});

vm.runInThisContext(fs.readFileSync(sourcePath, "utf8"), {
  filename: sourcePath,
});

const dispatch = (target, type, values) => {
  const event = {
    altKey: false,
    ctrlKey: false,
    metaKey: false,
    shiftKey: false,
    preventDefault() {},
    stopImmediatePropagation() {},
    ...values,
  };
  const callback = target.listeners.get(type);
  assert.ok(callback, `missing ${type} listener`);
  callback(event);
  return event;
};

const touch = (pointerId, clientX, clientY, extra = {}) => ({
  pointerId,
  pointerType: "touch",
  clientX,
  clientY,
  button: 0,
  buttons: 1,
  ...extra,
});

let state = window.ChurchPresenterRemoteView.getState();
assert.equal(state.zoom, 1);
assert.equal(state.fitScale, 0.25);
assert.equal(zoomLevel.textContent, "맞춤");

dispatch(canvas, "pointerdown", touch(1, 200, 400));
dispatch(canvas, "pointerup", touch(1, 200, 400, { buttons: 0 }));
assert.deepEqual(
  sent.map(({ type, action, x, y }) => ({ type, action, x, y })),
  [
    { type: "pointer", action: "press", x: 0.5, y: 0.5 },
    { type: "pointer", action: "release", x: 0.5, y: 0.5 },
  ],
);

sent.length = 0;
window.ChurchPresenterRemoteView.reset();
dispatch(canvas, "pointerdown", touch(10, 100, 400));
dispatch(canvas, "pointerdown", touch(11, 300, 400));
dispatch(canvas, "pointermove", touch(10, 50, 420));
dispatch(canvas, "pointermove", touch(11, 350, 420));
dispatch(canvas, "pointermove", touch(10, 80, 420));
dispatch(canvas, "pointermove", touch(11, 380, 420));
state = window.ChurchPresenterRemoteView.getState();
assert.equal(state.zoom, 1.5);
assert.ok(state.panX > 0);
assert.deepEqual(sent, [], "pinch and pan must not reach the remote input socket");

const contentX = 0.25 * state.frameWidth;
const contentY = 0.75 * state.frameHeight;
const transformedClientX = state.left + contentX * state.scale;
const transformedClientY = 50 + state.top + contentY * state.scale;
const normalized = window.ChurchPresenterRemoteView.normalizedAt(
  transformedClientX,
  transformedClientY,
);
assert.ok(Math.abs(normalized.x - 0.25) < 1e-9);
assert.ok(Math.abs(normalized.y - 0.75) < 1e-9);

dispatch(canvas, "pointerup", touch(10, 80, 420, { buttons: 0 }));
dispatch(canvas, "pointerup", touch(11, 380, 420, { buttons: 0 }));
dispatch(canvas, "dblclick", {
  pointerId: 99,
  pointerType: "mouse",
  clientX: 200,
  clientY: 400,
  button: 0,
  buttons: 0,
});
assert.deepEqual(sent, [], "synthetic double click after pinch must be blocked");

resetView.listeners.get("click")();
state = window.ChurchPresenterRemoteView.getState();
assert.equal(state.zoom, 1);
assert.equal(state.panX, 0);
assert.equal(state.panY, 0);

dispatch(canvas, "pointerdown", touch(20, 180, 390));
dispatch(canvas, "pointerup", touch(20, 180, 390, { buttons: 0 }));
sent.length = 0;
dispatch(canvas, "pointerdown", touch(21, 184, 394));
dispatch(canvas, "pointerup", touch(21, 184, 394, { buttons: 0 }));
state = window.ChurchPresenterRemoteView.getState();
assert.equal(state.zoom, 2);
assert.deepEqual(sent, [], "the second tap is a local view gesture");

lastSocket.onmessage({
  data: JSON.stringify({ width: 800, height: 450 }),
});
lastSocket.onmessage({ data: {} });
await new Promise((resolve) => setImmediate(resolve));
state = window.ChurchPresenterRemoteView.getState();
assert.equal(state.frameWidth, 800);
assert.equal(state.frameHeight, 450);
assert.equal(state.renderWidth, 800);
assert.equal(state.renderHeight, 450);
assert.equal(canvas.style.width, "800px");
assert.equal(canvas.style.height, "450px");

const anchorBeforeResize =
  window.ChurchPresenterRemoteView.normalizedAt(200, 400);
viewport.clientWidth = 700;
viewport.clientHeight = 400;
windowListeners.get("resize")();
state = window.ChurchPresenterRemoteView.getState();
const anchorAfterResize =
  window.ChurchPresenterRemoteView.normalizedAt(350, 250);
assert.equal(state.zoom, 2);
assert.ok(Math.abs(anchorAfterResize.x - anchorBeforeResize.x) < 1e-9);
assert.ok(Math.abs(anchorAfterResize.y - anchorBeforeResize.y) < 1e-9);

const decodeCalls = [];
const decodeOptions = [];
const pendingDecodes = [];
let activeDecodes = 0;
let maximumActiveDecodes = 0;
globalThis.createImageBitmap = (blob, options) => {
  decodeCalls.push(blob.id);
  decodeOptions.push(options);
  activeDecodes += 1;
  maximumActiveDecodes = Math.max(maximumActiveDecodes, activeDecodes);
  return new Promise((resolve) => {
    pendingDecodes.push(() => {
      activeDecodes -= 1;
      resolve({
        id: blob.id,
        close() {},
      });
    });
  });
};
drawnFrames.length = 0;
lastSocket.onmessage({
  data: JSON.stringify({ width: 1600, height: 900, sequence: 10 }),
});
lastSocket.onmessage({ data: { id: 10 } });
lastSocket.onmessage({
  data: JSON.stringify({ width: 1600, height: 900, sequence: 11 }),
});
lastSocket.onmessage({ data: { id: 11 } });
lastSocket.onmessage({
  data: JSON.stringify({ width: 1600, height: 900, sequence: 12 }),
});
lastSocket.onmessage({ data: { id: 12 } });
assert.deepEqual(decodeCalls, [10]);
assert.equal(decodeOptions[0].resizeWidth, 1024);
assert.equal(decodeOptions[0].resizeHeight, 576);
assert.equal(maximumActiveDecodes, 1);

sent.length = 0;
dispatch(canvas, "pointerdown", touch(30, 350, 250));
dispatch(canvas, "pointerup", touch(30, 350, 250, { buttons: 0 }));
assert.equal(sent.length, 2, "remote input must be sent during a slow decode");

pendingDecodes.shift()();
await new Promise((resolve) => setImmediate(resolve));
assert.deepEqual(decodeCalls, [10, 12], "the stale queued frame must be dropped");
assert.equal(maximumActiveDecodes, 1);
pendingDecodes.shift()();
await new Promise((resolve) => setImmediate(resolve));
state = window.ChurchPresenterRemoteView.getState();
assert.deepEqual(drawnFrames, [10, 12]);
assert.equal(state.droppedFrames, 1);
assert.equal(state.renderedSequence, 12);
assert.equal(state.renderWidth, 1024);
assert.equal(state.renderHeight, 576);

console.log("remote gesture tests passed");
