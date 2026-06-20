import requests
import csv
from datetime import datetime, timedelta
import time
import urllib.parse

def get_new_companies(days_back=180):
    # Вычисляем дату: сегодня минус 180 дней
    start_date_obj = datetime.now() - timedelta(days=days_back)
    start_date_str = start_date_obj.strftime('%Y-%m-%d')
    
    print(f"[*] Цель: собрать компании, зарегистрированные после {start_date_str} (последние полгода)")
    print("[*] Используем YTJ API v3 и метод смещения по ID для скорости...\n")

    # Официальный эндпоинт v3 из твоего CURL
    base_url = "https://avoindata.prh.fi/opendata-ytj-api/v3/companies"
    
    # Начинаем с номера 3380000-0. Это гарантирует, что мы в зоне свежих регистраций 2025-2026 годов.
    params = {
        "businessIdStart": "3380000-0", 
        "maxResults": 1000
    }
    
    url = f"{base_url}?{urllib.parse.urlencode(params)}"

    all_companies = []
    seen_ids = set()

    # Формы только для бизнеса (OY, TMI, KY, AY)
    good_forms = ["16", "26", "13", "14", "Osakeyhtiö", "Yksityinen elinkeinonharjoittaja", "Kommandiittiyhtiö", "Avoin yhtiö"]

    try:
        # Пройдем до 50 страниц, чтобы охватить все регистрации за полгода
        max_pages = 50
        current_page = 1
        
        while url and current_page <= max_pages:
            print(f"  [>] Запрос к API (Страница {current_page})...")
            
            headers = {
                "Accept": "application/json",
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
            }
            
            # Небольшая пауза, чтобы сервер не считал нас ботом
            time.sleep(0.4) 
            
            response = requests.get(url, headers=headers, timeout=20)
            
            if response.status_code == 404:
                print("  [-] Конец базы достигнут.")
                break
                
            response.raise_for_status()
            data = response.json()
            
            results = data.get('companies', data.get('results', []))
            if not results:
                break
                
            new_on_page = 0
            for company in results:
                # 1. Проверяем дату регистрации
                reg_date = company.get('registrationDate', '')
                if reg_date and reg_date >= start_date_str:
                    
                    # 2. Извлекаем Y-tunnus
                    y_data = company.get('businessId', '')
                    y_tunnus = y_data.get('value', '') if isinstance(y_data, dict) else str(y_data)
                    
                    # 3. Проверяем форму собственности (фильтруем жилые дома и фонды)
                    form_info = company.get('companyForm', '')
                    if not form_info and 'companyForms' in company:
                        forms = company.get('companyForms', [])
                        if forms: form_info = str(forms[0].get('type', ''))
                    
                    # Проверка на дубликаты и форму
                    if y_tunnus and y_tunnus not in seen_ids:
                        is_business = any(str(form_info).startswith(f) for f in good_forms)
                        if is_business:
                            seen_ids.add(y_tunnus)
                            all_companies.append(company)
                            new_on_page += 1
            
            print(f"      Найдено подходящих компаний на странице: {new_on_page}")
            
            # Переход на следующую страницу
            url = data.get('nextResultsUri')
            if not url and 'links' in data:
                for link in data['links']:
                    if link.get('rel') == 'next':
                        url = link.get('href')
                        break
            current_page += 1

        if not all_companies:
            print("\n[-] Новых компаний не найдено. Попробуйте уменьшить 'businessIdStart' в коде.")
            return

        # Записываем результат
        filename = f"finnish_b2b_6_months.csv"
        with open(filename, mode='w', encoding='utf-8-sig', newline='') as file:
            writer = csv.writer(file, delimiter=';')
            writer.writerow(['Y-tunnus', 'Название компании'])

            for comp in all_companies:
                y_data = comp.get('businessId', '')
                y_val = y_data.get('value', '') if isinstance(y_data, dict) else str(y_data)
                
                # Имя компании
                c_name = comp.get('name', '')
                if not c_name and 'names' in comp:
                    names = comp.get('names', [])
                    if names: c_name = names[0].get('name', '')
                
                writer.writerow([y_val, c_name])

        print(f"\n[+] ГОТОВО! Собрано {len(all_companies)} компаний.")
        print(f"[+] Файл сохранен: {filename}")

    except Exception as e:
        print(f"[!] Ошибка: {e}")

if __name__ == "__main__":
    get_new_companies(180) # Поиск за 180 дней