daemonize = false
pidfile = "/var/run/prosody/prosody.pid"
log = {
  info = "*console";
  debug = "*console";
}

allow_registration = true
c2s_require_encryption = false
s2s_require_encryption = false
allow_unencrypted_plain_auth = true
authentication = "internal_plain"

modules_enabled = {
  "tls";
  "roster";
  "saslauth";
  "disco";
  "private";
  "version";
  "uptime";
  "time";
  "ping";
  "register";
}

modules_disabled = {
  "s2s";
  "bosh";
  "websocket";
}

VirtualHost "xmpp"
ssl = {
  key = "/var/lib/prosody/xmpp.key";
  certificate = "/var/lib/prosody/xmpp.crt";
}
