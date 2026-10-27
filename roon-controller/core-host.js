'use strict';

// A Roon Core address from Settings: a hostname or IPv4/IPv6 literal, never a URL or a path.
function validCoreHost(value) {
  const host = String(value || '').trim();
  return /^[A-Za-z0-9]([A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$/.test(host) || /^[0-9A-Fa-f:]{2,45}$/.test(host) && host.includes(':') ? host : '';
}

// Discovery (daily mixes, library actions) needs the Core's address and broker id, which normally arrive in a broadcast
// that cannot cross a VPN. For a directly connected Core they are known already: the Core id is the broadcast's unique id.
function directDiscoveryTarget(host, coreId) {
  const {brokerWireId} = require('../tools/discovery-wire.cjs');
  try { return validCoreHost(host) ? {host, httpPort: 9330, brokerId: brokerWireId(coreId)} : null; }
  catch { return null; }
}

module.exports = {validCoreHost, directDiscoveryTarget};
