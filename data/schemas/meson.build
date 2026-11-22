install_data('io.github.deskence.Deskence.gschema.xml',
  install_dir: datadir / 'glib-2.0' / 'schemas')

# Compiled copy for running from the build directory and for tests.
gnome.compile_schemas(build_by_default: true)

compile_schemas = find_program('glib-compile-schemas', required: false)
if compile_schemas.found()
  test('validate-schema', compile_schemas,
    args: ['--strict', '--dry-run', meson.current_source_dir()])
endif

subdir('legacy')
