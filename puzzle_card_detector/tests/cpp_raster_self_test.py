import pathlib
import subprocess
import tempfile


def main():
    source = pathlib.Path(__file__).with_name('cpp_raster_test.cpp')
    with tempfile.TemporaryDirectory(prefix='puzzle-raster-test-') as directory:
        binary = str(pathlib.Path(directory) / 'raster_test')
        subprocess.run(['g++', '-O3', '-march=native', '-pthread', '-std=c++17',
                        str(source), '-o', binary], check=True)
        subprocess.run([binary], check=True)


if __name__ == '__main__':
    main()
