'use strict';

// A Roon Core address from Settings: a hostname or IPv4/IPv6 literal, never a URL or a path.
function validCoreHost(value) {
  const host = String(value || '').trim();
  return /^[A-Za-z0-9]([A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$/.test(host) || /^[0-9A-Fa-f:]{2,45}$/.test(host) && host.includes(':') ? host : '';
}

module.exports = {validCoreHost};
