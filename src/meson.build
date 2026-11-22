gnome.compile_resources('deskence',
  'deskence/ui/deskence.gresource.xml',
  source_dir: 'deskence/ui',
  gresource_bundle: true,
  install: true,
  install_dir: pkgdatadir,
)

configure_file(
  input: 'deskence.in',
  output: 'deskence',
  configuration: conf,
  install_dir: bindir,
  install_mode: 'rwxr-xr-x',
)

# The former command, for shortcuts and scripts made before the rename.
install_symlink(legacy_name,
  pointing_to: 'deskence',
  install_dir: bindir,
)

install_subdir('deskence',
  install_dir: pkgdatadir,
  exclude_directories: ['__pycache__', 'ui'],
)
