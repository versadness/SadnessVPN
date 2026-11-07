'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { EventEmitter } = require('node:events');

function load(name, mocks) {
  const source = fs.readFileSync(path.join(__dirname, '../electron/lib', name), 'utf8');
  const module = { exports: {} };
  vm.runInNewContext(source, {
    module, console, process, setTimeout, clearTimeout,
    require: (id) => Object.hasOwn(mocks, id) ? mocks[id] : require(id),
  }, { filename: name });
  return module.exports;
}

function backendFixture(version) {
  let running = true;
  const requests = [];
  const respond = (callback, payload) => {
    const response = new EventEmitter();
    response.statusCode = 200;
    response.resume = () => {};
    callback(response);
    response.emit('data', JSON.stringify(payload));
    response.emit('end');
  };
  const backend = load('backend.js', {
    electron: { app: { getVersion: () => '3.4.8' } },
    './paths': { PROJECT_ROOT: '/project', dataDir: () => '/profile' },
    fs: { readFileSync: () => 'T'.repeat(43) },
    http: {
      get(options, callback) {
        const req = new EventEmitter();
        process.nextTick(() => respond(callback, running ? { app: 'SadnessVPN', version } : {}));
        return req;
      },
      request(options, callback) {
        requests.push(options);
        const req = new EventEmitter();
        req.end = () => {
          running = false;
          process.nextTick(() => respond(callback, {}));
        };
        return req;
      },
    },
  });
  return { backend, requests };
}

test('refusing another version never shuts down its backend', async () => {
  const { backend, requests } = backendFixture('3.4.7');
  assert.equal((await backend.start()).ok, false);
  await backend.stop();
  assert.equal(requests.length, 0);
});

test('quitting before attachment never shuts down another instance', async () => {
  const { backend, requests } = backendFixture('3.4.8');
  await backend.stop();
  assert.equal(requests.length, 0);
});

test('an attached backend still receives authenticated graceful shutdown', async () => {
  const { backend, requests } = backendFixture('3.4.8');
  assert.equal((await backend.start()).ok, true);
  await backend.stop();
  assert.equal(requests.length, 1);
  assert.equal(requests[0].path, '/api/shell/shutdown');
  assert.equal(requests[0].headers['X-Sadness-Token'], 'T'.repeat(43));
});

test('an asynchronous backend spawn error is reported without crashing Electron', async () => {
  const backend = load('backend.js', {
    electron: { app: { isPackaged: false, getVersion: () => '3.4.8' } },
    './paths': { PROJECT_ROOT: '/project', dataDir: () => '/profile' },
    fs: { existsSync: () => true, unlinkSync: () => {} },
    child_process: {
      spawn() {
        const child = new EventEmitter();
        process.nextTick(() => child.emit('error', new Error('spawn EACCES')));
        return child;
      },
    },
    http: {
      get(options, callback) {
        const req = new EventEmitter();
        process.nextTick(() => {
          const response = new EventEmitter();
          callback(response);
          response.emit('data', '{}');
          response.emit('end');
        });
        return req;
      },
    },
  });
  const start = Date.now();
  const result = await backend.start();
  assert.equal(result.ok, false);
  assert.match(result.error, /EACCES/);
  assert.ok(Date.now() - start < 2000, 'spawn failure should not wait for the health timeout');
});

function windowState(saved) {
  return load('window-state.js', {
    fs: { readFileSync: () => JSON.stringify(saved) },
    './paths': { dataDir: () => '/profile' },
    electron: { screen: { getAllDisplays: () => [{ workArea: { x: 0, y: 0, width: 1920, height: 1080 } }] } },
  }).load();
}

test('invalid window-state JSON values fall back without crashing startup', () => {
  for (const value of [null, [], true, 'broken']) {
    const state = windowState(value);
    assert.equal(state.width, 1377);
    assert.equal(state.height, 788);
    assert.equal(state.maximized, false);
  }
});

test('non-finite window sizes never reach BrowserWindow', () => {
  const state = windowState({ width: 'Infinity', height: '1e999' });
  assert.equal(state.width, 1377);
  assert.equal(state.height, 788);
  const malformed = windowState({ width: { valueOf: 1, toString: 1 }, height: 1e100 });
  assert.equal(malformed.width, 1377);
  assert.equal(malformed.height, 788);
});

test('valid bounds and maximized state survive normalization', () => {
  const state = windowState({ width: 1200, height: 800, x: 20, y: 30, maximized: true });
  assert.equal(state.width, 1200);
  assert.equal(state.height, 800);
  assert.equal(state.x, 20);
  assert.equal(state.maximized, true);
});
