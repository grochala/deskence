i18n.gettext(gettext_package, preset: 'glib')

# Regional variants without a translation of their own use the closest one,
# as a link, so that gettext finds it for their locales everywhere (the
# settings window, the desktop icons and the GNOME Shell extensions):
# gettext only falls back from zh_HK to zh, not to zh_TW. The language list
# of Deskence skips links (src/deskence/languages.py).
locale_aliases = {
  'zh_HK': 'zh_TW',
  'zh_MO': 'zh_TW',
  'zh_SG': 'zh_CN',
}
foreach alias, target : locale_aliases
  install_symlink(gettext_package + '.mo',
    pointing_to: '../..' / target / 'LC_MESSAGES' / gettext_package + '.mo',
    install_dir: localedir / alias / 'LC_MESSAGES',
  )
endforeach

# Checks of the translations: every catalog compiles, matches the template
# and keeps the placeholders, mnemonics and plural forms of the original
# (po/check-po.py).
msgfmt = find_program('msgfmt', required: false)
if get_option('tests') and msgfmt.found()
  test('check-po', python3,
    args: [meson.current_source_dir() / 'check-po.py', '--check'],
    env: ['MSGFMT=' + msgfmt.full_path()],
  )
endif

# Completeness of each translation, for translators:
#   meson compile -C _build deskence-po-status
run_target(gettext_package + '-po-status',
  command: [python3, meson.current_source_dir() / 'check-po.py', '--status'],
)
