project('recursive extract all and partial only deps', 'c',
  version : '0.1',
  default_options : ['warning_level=3'],
  meson_version: '>=1.6.0')

if meson.backend() == 'xcode'
    error('MESON_SKIP_TEST: Xcode backend does not handle libraries with only objects, not sources.')
endif

internal_static = static_library('testmesonlib', 'testmesonlib.c',
    dependencies: [dependency('glib-2.0')])

lib = static_library('testmeson', link_whole: internal_static, install : true)

dep = declare_dependency(link_with: lib)
partial = dep.partial_dependency(link_args: true, links: true, only_exts: true)

objects = lib.extract_all_objects(recursive: true)
fulllib = static_library('fulllib', objects: objects, dependencies: [partial])

fulllib_dep = declare_dependency(link_with: fulllib)

exe = executable('testmeson', 'testmeson.c', install : true, link_with: [lib])

pkgconfig = import('pkgconfig')
pkgconfig.generate(fulllib)

test('basic', exe)
test('check-pc', find_program('check_pc.py'), args: [meson.build_root()])

