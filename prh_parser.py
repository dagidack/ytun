import requests
import csv
from datetime import datetime, timedelta
import time

def get_new_companies(days_back=60):
    # ВАЖНО: Если на твоем компьютере 2026 год, а сервер в 2025, 
    # мы принудительно откатимся назад для теста, чтобы ты увидел данные.
    now = datetime.now()
    if now.year > 2025:
        # Если мы в "будущем", будем искать от начала 2025 года
        start_date_obj = datetime(2025, 1, 1)
        print("[!] Внимание: Обнаружена дата из будущего. Ищем записи с 2025 года для теста.")
    else:
        start_date_obj = now - timedelta(days=days_back)

    end_date_obj = start_date_obj + timedelta(days=days_back)
    
    print(f"[*] Сбор B2B компаний Финляндии.")
    print(f"[*] Период: {start_date_obj.strftime('%Y-%m-%d')} — {end_date_obj.strftime('%Y-%m-%d')}\n")

    # API v1 — единственный, кто умеет искать по датам (registrationFrom)
    base_url = "https://avoindata.prh.fi/bis/v1"
    
    all_companies = []
    seen_ids = set()

    # Фильтруем формы, которые обычно интересны в B2B
    target_forms = ["osakeyhtiö", "oy", "tmi", "ky", "ay", "ltd"]

    # Шагаем по 10 дней
    current_start = start_date_obj
    while current_start <= end_date_obj:
        current_end = current_start + timedelta(days=9)
        
        d_from = current_start.strftime('%Y-%m-%d')
        d_to = current_end.strftime('%Y-%m-%d')

        print(f"  [>] Запрос: {d_from} ... {d_to}", end=" -> ", flush=True)

        params = {
            "registrationFrom": d_from,
            "registrationTo": d_to,
            "maxResults": 1000,
            "totalResults": "false"
        }
        
        try:
            # Используем базовый URL без /companies (так работает поиск в v1)
            response = requests.get(base_url, params=params, timeout=20)
            
            if response.status_code == 200:
                results = response.json().get('results', [])
                found_b2b = 0
                for comp in results:
                    y_id = comp.get('businessId')
                    form = str(comp.get('companyForm', '')).lower()
                    
                    if any(target in form for target in target_forms):
                        if y_id and y_id not in seen_ids:
                            seen_ids.add(y_id)
                            all_companies.append({
                                'y_id': y_id,
                                'name': comp.get('name'),
                                'form': comp.get('companyForm'),
                                'date': comp.get('registrationDate')
                            })
                            found_b2b += 1
                print(f"Найдено B2B: {found_b2b}")
            elif response.status_code == 404:
                print("Пусто")
            else:
                print(f"Ошибка {response.status_code}")

        except Exception as e:
            print(f"Сбой: {e}")

        time.sleep(0.5)
        current_start = current_end + timedelta(days=1)

    if all_companies:
        filename = f"finnish_leads.csv"
        with open(filename, mode='w', encoding='utf-8-sig', newline='') as file:
            writer = csv.writer(file, delimiter=';')
            writer.writerow(['Y-tunnus', 'Название', 'Тип', 'Дата регистрации'])
            for c in all_companies:
                writer.writerow([c['y_id'], c['name'], c['form'], c['date']])
        print(f"\n[+] ИТОГО: {len(all_companies)} компаний сохранено в {filename}")
    else:
        print("\n[-] Ничего не найдено. Проверьте, не слишком ли свежая дата.")

if __name__ == "__main__":
    get_new_companies(30)