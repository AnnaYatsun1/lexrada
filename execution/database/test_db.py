from execution.database.db import (
    init_db,
    compute_file_hash,
    is_already_processed,
    record_start,
    record_success,
    record_failure,
)
from pathlib import Path

# 1. Создаём БД
init_db()
print("✅ БД создана")

# 2. Берём любой существующий файл из input_contracts
test_file = Path("input_contracts/contract_1.txt")  # подставь свой путь
file_hash = compute_file_hash(test_file)
print(f"✅ Hash файла: {file_hash[:16]}...")

# 3. Проверяем — обработан или нет
print(f"Уже обработан? {is_already_processed(file_hash)}")

# 4. Помечаем как начатый
pid = record_start(file_hash, test_file.name)
print(f"✅ Запись начата, id={pid}")

# 5. Помечаем как успешный
record_success(pid, "output/test_result.md")
print(f"✅ Запись завершена")

# 6. Снова проверяем
print(f"Уже обработан после success? {is_already_processed(file_hash)}")