project('a', 'c')

b_dep = dependency('b', fallback : ['b', 'b_dep'])

l = shared_library('a', 'a.c', dependencies : b_dep)
