project('cargo virtual workspace', 'rust')

rust = import('unstable-rust')

exe = executable('main', 'main.rs',
    dependencies : dependency('sub')
)
test('main', exe)

exe = executable('main2', 'main2.rs',
    dependencies : dependency('anothersub')
)
test('main2', exe)

