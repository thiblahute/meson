project('b', 'c')

gen_h = find_program('genh.py')

h = custom_target('b_h',
  output : 'b.h', command : [gen_h, '@OUTPUT@'])

lb = shared_library('b', 'b.c', h)

b_dep = declare_dependency(link_with : lb,
  include_directories : [include_directories('.')],
  sources : [h])
