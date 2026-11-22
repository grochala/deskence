tray_dir = extensions_dir / extension_uuids['tray']

configure_file(
  input: 'metadata.json.in',
  output: 'metadata.json',
  configuration: conf,
  install_dir: tray_dir,
)

install_data(
  'extension.js',
  'watcher.js',
  'trayItem.js',
  'dbusMenuModel.js',
  install_dir: tray_dir,
)
