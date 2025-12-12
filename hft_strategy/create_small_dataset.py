import numpy as np
import sys
import os

def create_small_dataset(input_path, output_path, num_rows=1000):
    """
    Создает маленький тестовый датасет из большого файла
    """
    print(f"Creating small dataset with {num_rows} rows from {input_path}")
    
    # Загружаем большой датасет
    try:
        full_data = np.load(input_path)['data']
        print(f"Full dataset shape: {full_data.shape}")
        
        if len(full_data) < num_rows:
            print(f"Warning: requested {num_rows} rows but dataset only has {len(full_data)} rows")
            num_rows = len(full_data)
        
        # Берем первые num_rows строк
        small_data = full_data[:num_rows]
        print(f"Small dataset shape: {small_data.shape}")
        
        # Сохраняем маленький датасет
        np.savez_compressed(output_path, data=small_data)
        print(f"Small dataset saved to {output_path}")
        
        # Показываем примеры данных
        print("Sample of first 5 rows:")
        for i in range(min(5, len(small_data))):
            print(f"  Row {i}: {small_data[i]}")
            
    except FileNotFoundError:
        print(f"Error: Input file {input_path} not found")
        return False
    except Exception as e:
        print(f"Error creating small dataset: {e}")
        return False
    
    return True

if __name__ == "__main__":
    # Проверяем аргументы командной строки
    input_file = "data/SOLUSDT_v2.npz"
    output_file = "data/SOLUSDT_small_test.npz"
    
    if len(sys.argv) > 1:
        input_file = sys.argv[1]
    if len(sys.argv) > 2:
        output_file = sys.argv[2]
    if len(sys.argv) > 3:
        num_rows = int(sys.argv[3])
    else:
        num_rows = 1000
    
    success = create_small_dataset(input_file, output_file, num_rows)
    if success:
        print("Success!")
    else:
        print("Failed!")
        sys.exit(1)