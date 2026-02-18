pkgdatadir = get_option('prefix') / get_option('datadir') / meson.project_name()
moduledir = pkgdatadir / 'win2xcur_gui'
gnome = import('gnome')

gnome.compile_resources('win2xcur-gui',
  'win2xcur-gui.gresource.xml',
  gresource_bundle: true,
  install: true,
  install_dir: pkgdatadir,
)

python = import('python')

conf = configuration_data()
conf.set('PYTHON', python.find_installation('python3').full_path())
conf.set('VERSION', meson.project_version())
conf.set('localedir', get_option('prefix') / get_option('localedir'))
conf.set('pkgdatadir', pkgdatadir)

configure_file(
  input: 'win2xcur-gui.in',
  output: 'win2xcur-gui',
  configuration: conf,
  install: true,
  install_dir: get_option('bindir'),
  install_mode: 'rwxr-xr-x'
)

win2xcur_gui_sources = [
  '__init__.py',
  'main.py',
  'window.py',
  'constants.py',
  'models.py',
  'converter.py',
  'cursor_preview.py',
]

install_data(win2xcur_gui_sources, install_dir: moduledir)
