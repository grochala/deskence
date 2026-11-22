configure_file(
  input: 'deskence-desktop-icons.in',
  output: conf.get('HELPER_NAME'),
  configuration: conf,
  install_dir: libexecdir,
  install_mode: 'rwxr-xr-x',
)

# After an update GNOME Shell keeps running the previous extension until the
# next login, and that one starts the helper by its former path.
install_symlink('better-gnome-desktop-icons',
  pointing_to: conf.get('HELPER_NAME'),
  install_dir: libexecdir,
)

install_subdir('deskence_desktop',
  install_dir: pkgdatadir,
  exclude_directories: ['__pycache__'],
)
