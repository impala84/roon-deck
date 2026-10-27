'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const {validCoreHost, directDiscoveryTarget} = require('./core-host');

test('Roon Core addresses accept hosts and IPs only', () => {
  for (const good of ['192.168.1.20', 'roon.local', 'core-1']) assert.equal(validCoreHost(good), good);
  assert.equal(validCoreHost(' 10.0.0.5 '), '10.0.0.5');
  for (const bad of ['', 'http://10.0.0.5', '10.0.0.5:9330', 'a b', '../x', null]) assert.equal(validCoreHost(bad), '');
});

test('a directly connected Core gets a discovery target without a broadcast', () => {
  assert.deepEqual(directDiscoveryTarget('10.12.0.20', 'b1061bf7-37f6-4f09-aa76-ae7776f56bd0'), {host: '10.12.0.20', httpPort: 9330, brokerId: 'f71b06b1f637094faa76ae7776f56bd0'});
  assert.equal(directDiscoveryTarget('10.12.0.20', 'not-a-uuid'), null);
  assert.equal(directDiscoveryTarget('http://bad', 'b1061bf7-37f6-4f09-aa76-ae7776f56bd0'), null);
});
