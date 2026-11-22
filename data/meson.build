desktop_file = i18n.merge_file(
  input: configure_file(
    input: 'io.github.deskence.Deskence.desktop.in.in',
    output: 'io.github.deskence.Deskence.desktop.in',
    configuration: conf,
  ),
  output: app_id + '.desktop',
  type: 'desktop',
  po_dir: '../po',
  install: true,
  install_dir: datadir / 'applications',
)

desktop_file_validate = find_program('desktop-file-validate', required: false)
if desktop_file_validate.found()
  test('validate-desktop', desktop_file_validate, args: [desktop_file])
endif

metainfo_file = i18n.merge_file(
  input: 'io.github.deskence.Deskence.metainfo.xml.in',
  output: app_id + '.metainfo.xml',
  po_dir: '../po',
  install: true,
  install_dir: datadir / 'metainfo',
)

appstreamcli = find_program('appstreamcli', required: false)
if appstreamcli.found()
  test('validate-metainfo', appstreamcli,
    args: ['validate', '--no-net', '--explain', metainfo_file])
endif

configure_file(
  input: 'io.github.deskence.Deskence.service.in',
  output: app_id + '.service',
  configuration: conf,
  install_dir: datadir / 'dbus-1' / 'services',
)

# Taking over an installation of Better GNOME Desktop, the former name (see
# src/deskence/rename.py): at every login, before GNOME Shell enables the
# extensions with the new names...
configure_file(
  input: 'deskence-migration.desktop.in',
  output: 'deskence-migration.desktop',
  configuration: conf,
  install_dir: get_option('sysconfdir') / 'xdg' / 'autostart',
)

# ...and the former D-Bus name, activated by the menus of the former
# extensions, which keep running until the next login after an update.
configure_file(
  input: 'legacy.service.in',
  output: legacy_app_id + '.service',
  configuration: conf,
  install_dir: datadir / 'dbus-1' / 'services',
)

# The manual page, kept by hand, and the same page for the former command.
man_page = configure_file(
  input: 'deskence.1.in',
  output: 'deskence.1',
  configuration: conf,
)
install_man(man_page)

# groff prints nothing for a page without mistakes.
groff = find_program('groff', required: false)
if groff.found()
  test('validate-man', find_program('sh'),
    args: ['-c', 'out=$("$1" -man -z -ww "$2" 2>&1) && [ -z "$out" ] || { echo "$out"; exit 1; }',
           'sh', groff.full_path(), man_page])
endif
install_data('better-gnome-desktop.1', install_dir: get_option('mandir') / 'man1')

subdir('schemas')

install_subdir('icons/hicolor', install_dir: datadir / 'icons')
