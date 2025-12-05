import sys
import os

# Трюк: добавляем путь к скомпилированному файлу в Python
# Обычно CMake кладет его в build/Release или просто build
# Мы проверим оба места
build_path_release = os.path.join(os.getcwd(), 'hft_core', 'build', 'Release')
build_path_root = os.path.join(os.getcwd(), 'hft_core', 'build')

if os.path.exists(build_path_release):
    sys.path.append(build_path_release)
    print(f"Adding to path: {build_path_release}")
elif os.path.exists(build_path_root):
    sys.path.append(build_path_root)
    print(f"Adding to path: {build_path_root}")

try:
    import hft_core
    print("\n✅ УСПЕХ! Модуль hft_core успешно импортирован!")
    print(f"Документация модуля: {hft_core.__doc__}")
except ImportError as e:
    print(f"\n❌ ОШИБКА ИМПОРТА: {e}")
    print("Убедись, что файл .pyd существует в папке build/Release")
except Exception as e:
    print(f"\n❌ Критическая ошибка: {e}")