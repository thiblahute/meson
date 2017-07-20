project('a', 'c')

b_dep = dependency('b', fallback: ['b', 'b_dep'], required: false)
l = shared_library('a', 'a.c')
