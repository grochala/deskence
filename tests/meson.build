pytest = find_program('pytest', 'pytest-3', required: false)
if pytest.found()
  test('unit-python', pytest,
    args: ['-q', '-p', 'no:cacheprovider', meson.current_source_dir() / 'unit'])
endif

gjs = find_program('gjs', required: false)
if gjs.found()
  test('unit-gjs', gjs, args: ['-m', meson.current_source_dir() / 'unit' / 'test_dbusmenu.js'])
  test('unit-gjs-geometry', gjs,
    args: ['-m', meson.current_source_dir() / 'unit' / 'test_geometry.js'])
  test('unit-gjs-keep-awake', gjs,
    args: ['-m', meson.current_source_dir() / 'unit' / 'test_keep_awake.js'])
  test('unit-gjs-clipboard', gjs,
    args: ['-m', meson.current_source_dir() / 'unit' / 'test_clipboard.js'])
  test('unit-gjs-launcher', gjs,
    args: ['-m', meson.current_source_dir() / 'unit' / 'test_launcher.js'])
  test('unit-gjs-stacks', gjs,
    args: ['-m', meson.current_source_dir() / 'unit' / 'test_stacks.js'])
  test('unit-gjs-order', gjs,
    args: ['-m', meson.current_source_dir() / 'unit' / 'test_order.js'],
    env: ['LANG=pl_PL.UTF-8'])
endif
