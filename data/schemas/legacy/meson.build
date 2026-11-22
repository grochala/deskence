# The schema under the former ID and path, only to take over the settings
# of Better GNOME Desktop (src/deskence/rename.py). Compiled into the
# package data folder, not installed among the system schemas.
legacy_schema = custom_target('legacy-schema-xml',
  input: '..' / 'io.github.deskence.Deskence.gschema.xml',
  output: legacy_app_id + '.gschema.xml',
  command: [python3, files('..' / 'make-legacy-schema.py'), '@INPUT@', '@OUTPUT@'],
)
legacy_schemas_dir = pkgdatadir / 'legacy-schemas'
custom_target('legacy-schema',
  input: legacy_schema,
  output: 'gschemas.compiled',
  command: [find_program('glib-compile-schemas'), '--strict', '--targetdir=@OUTDIR@',
    '@OUTDIR@'],
  build_by_default: true,
  install: true,
  install_dir: legacy_schemas_dir,
)
