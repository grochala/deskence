project('deskence',
  version: '0.10.0',
  license: 'GPL-3.0-or-later',
  meson_version: '>= 1.0.0',
)

gnome = import('gnome')
i18n = import('i18n')
python = import('python')

# The application ID: D-Bus name, desktop file, AppStream ID, icons and
# GSettings schema.
app_id = 'io.github.deskence.Deskence'
gettext_package = meson.project_name()

# Identifiers of the project's former name, Better GNOME Desktop (up to
# 0.3.0). They are only used to migrate an existing installation (settings,
# enabled extensions, data folders) and for compatibility symlinks; see
# docs/architecture.md, ADR 13.
legacy_app_id = 'io.github.bettergnome.Desktop'
legacy_name = 'better-gnome-desktop'

prefix = get_option('prefix')
bindir = prefix / get_option('bindir')
datadir = prefix / get_option('datadir')
libexecdir = prefix / get_option('libexecdir')
localedir = prefix / get_option('localedir')
pkgdatadir = datadir / meson.project_name()
extensions_dir = datadir / 'gnome-shell' / 'extensions'

python3 = python.find_installation('python3')

# UUIDs of our GNOME Shell extensions. The package owns these directories
# under the system extension directory; nothing is copied to the user's home.
extension_uuids = {
  'dock': 'dock@deskence.github.io',
  'desktop': 'desktop-icons@deskence.github.io',
  'tray': 'tray@deskence.github.io',
  'app-grid': 'app-grid@deskence.github.io',
  'clipboard': 'clipboard@deskence.github.io',
  'keep-awake': 'keep-awake@deskence.github.io',
}

conf = configuration_data()
conf.set('APP_ID', app_id)
conf.set('VERSION', meson.project_version())
conf.set('GETTEXT_PACKAGE', gettext_package)
conf.set('PKGDATADIR', pkgdatadir)
conf.set('LOCALEDIR', localedir)
conf.set('LIBEXECDIR', libexecdir)
conf.set('BINDIR', bindir)
conf.set('PYTHON', python3.full_path())
conf.set('UUID_DOCK', extension_uuids['dock'])
conf.set('UUID_DESKTOP', extension_uuids['desktop'])
conf.set('UUID_TRAY', extension_uuids['tray'])
conf.set('UUID_APP_GRID', extension_uuids['app-grid'])
conf.set('UUID_CLIPBOARD', extension_uuids['clipboard'])
conf.set('UUID_KEEP_AWAKE', extension_uuids['keep-awake'])
conf.set('LEGACY_APP_ID', legacy_app_id)
conf.set('HELPER_NAME', meson.project_name() + '-desktop-icons')
conf.set('SHELL_VERSIONS', '"' + '", "'.join(get_option('shell_versions')) + '"')

subdir('data')
subdir('src')
subdir('desktop-icons')
subdir('extensions')
subdir('po')

if get_option('tests')
  subdir('tests')
endif

gnome.post_install(
  glib_compile_schemas: true,
  gtk_update_icon_cache: true,
  update_desktop_database: true,
)
