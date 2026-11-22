app_grid_dir = extensions_dir / extension_uuids['app-grid']

configure_file(
  input: 'metadata.json.in',
  output: 'metadata.json',
  configuration: conf,
  install_dir: app_grid_dir,
)

install_data(
  'extension.js',
  'sorter.js',
  'order.js',
  install_dir: app_grid_dir,
)
