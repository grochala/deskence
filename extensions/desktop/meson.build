desktop_dir = extensions_dir / extension_uuids['desktop']

configure_file(
  input: 'metadata.json.in',
  output: 'metadata.json',
  configuration: conf,
  install_dir: desktop_dir,
)

install_data('extension.js', 'areas.js', 'menu.js', install_dir: desktop_dir)
