keep_awake_dir = extensions_dir / extension_uuids['keep-awake']

configure_file(
  input: 'metadata.json.in',
  output: 'metadata.json',
  configuration: conf,
  install_dir: keep_awake_dir,
)

install_data(
  'extension.js',
  'timing.js',
  'stylesheet.css',
  install_dir: keep_awake_dir,
)
