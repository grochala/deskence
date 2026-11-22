dock_dir = extensions_dir / extension_uuids['dock']

configure_file(
  input: 'metadata.json.in',
  output: 'metadata.json',
  configuration: conf,
  install_dir: dock_dir,
)

install_data(
  'extension.js',
  'dock.js',
  'appFolders.js',
  'appIcon.js',
  'launcherEntry.js',
  'launcherLogic.js',
  'locations.js',
  'logic.js',
  'logo.js',
  'magnifier.js',
  'overviewBackdrop.js',
  'peek.js',
  'startup.js',
  'stackLogic.js',
  'stacks.js',
  'windowPreviews.js',
  'stylesheet.css',
  install_dir: dock_dir,
)
