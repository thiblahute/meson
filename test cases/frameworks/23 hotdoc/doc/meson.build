hotdoc = import('hotdoc')

target = hotdoc.generate_doc(
  'foobar',
  c_smart_index: true,
  project_version: '0.1',
  sitemap: 'sitemap.txt',
  index: 'index.md',
  c_sources: '../../10 gtk-doc/include/foo.h',
  languages: ['c'],
  install: true,
)

assert(target.config_path() == target.full_path() + '.json',
  'Hotdoc config paths do not match.'
)

assert(hotdoc.has_extensions('search') == true,
  'Extension "search" provided by hotdoc core should always be found')

add_global_arguments('-DMESON_TEST', language : 'c')
gir_sub = subproject('mesongir')

girlib = gir_sub.get_variable('girlib')
target = hotdoc.generate_doc('girlib',
  index: 'index.md',
  c_smart_index: true,
  project_version: '0.1',
  documented_targets: girlib,
  install: true,
)

girtarget = gir_sub.get_variable('girtarget')
target = hotdoc.generate_doc('girtarget',
  index: 'index.md',
  gi_smart_index: true,
  project_version: '0.1',
  documented_targets: girtarget,
  install: true,
)