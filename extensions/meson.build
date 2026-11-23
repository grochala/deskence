subdir('dock')
subdir('desktop')
subdir('tray')
subdir('app-grid')
subdir('clipboard')
subdir('keep-awake')

# GNOME Shell reads the translations of an extension from a "locale" folder
# inside it, or else from its own locale directory (/usr/share/locale). With
# another prefix, the extensions get a link to ours.
if localedir != '/usr/share/locale'
  foreach name, uuid : extension_uuids
    install_symlink('locale', pointing_to: localedir, install_dir: extensions_dir / uuid)
  endforeach
endif
