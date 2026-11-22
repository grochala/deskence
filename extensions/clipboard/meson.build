clipboard_dir = extensions_dir / extension_uuids['clipboard']

configure_file(
  input: 'metadata.json.in',
  output: 'metadata.json',
  configuration: conf,
  install_dir: clipboard_dir,
)

install_data(
  'extension.js',
  'history.js',
  'panel.js',
  'storage.js',
  'stylesheet.css',
  install_dir: clipboard_dir,
)
