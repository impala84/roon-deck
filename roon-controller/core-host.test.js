'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const {validCoreHost} = require('./core-host');

test('Roon Core addresses accept hosts and IPs only', () => {
  for (const good of ['192.168.1.20', 'roon.local', 'core-1']) assert.equal(validCoreHost(good), good);
  assert.equal(validCoreHost(' 10.0.0.5 '), '10.0.0.5');
  for (const bad of ['', 'http://10.0.0.5', '10.0.0.5:9330', 'a b', '../x', null]) assert.equal(validCoreHost(bad), '');
});
