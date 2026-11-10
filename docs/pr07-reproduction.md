# Запуск ПР7

Продовжуйте той самий проєкт після [ПР6](pr06-reproduction.md).
Для CPU-досліду використовується `MODEL=qwen3:0.6b` у локальному `.env`.
Образ Ollama та ваги моделі завантажуються окремо; забезпечте достатньо
дискового простору для обох, а не лише для маленької моделі.

```sh
docker pull grafana/grafana@sha256:488984b716c0862639f91a698adbe2862677a5a07bad42da5f03f3030883b205
docker tag grafana/grafana@sha256:488984b716c0862639f91a698adbe2862677a5a07bad42da5f03f3030883b205 grafana/grafana:13.3.0
docker pull ollama/ollama@sha256:b2f0122c476bc9fe7ce679d8bb4bd555351e25e2554eefb156f61cb0a89cf429
docker tag ollama/ollama@sha256:b2f0122c476bc9fe7ce679d8bb4bd555351e25e2554eefb156f61cb0a89cf429 ollama/ollama:0.40.13
sh tests/compose.sh pr07 --profile monitoring --profile ai up -d
sh tests/compose.sh pr07 exec -T ollama ollama pull qwen3:0.6b
sh tests/check.sh pr07
```

Образи беруться з незміненого `tests/images.lock.json`; тести не змінюються.
Grafana доступна лише на `http://127.0.0.1:3000/d/netlab`. Додаткова мережа
ingress потрібна для localhost-порту; control залишається внутрішньою.
Ollama API на хост не публікується, хмарний режим вимкнено, Docker socket
і засоби виконання рекомендованих дій моделі не надаються.

Джерело обох панелей — Blackbox через Prometheus; мітка instance визначає
ціль. `HTTP probe success` має значення 0/1, а `HTTP probe duration (s)` —
тривалість HTTP-проби в секундах, не ICMP RTT. Панелі показують останні
п'ять хвилин і оновлюються кожні п'ять секунд.

Повна перевірка виконує три реальні локальні запити: normal, incident і
limited. Форму JSON і наявність E-ID перевіряє тест; причинні твердження
потрібно порівнювати з evidence.json, навіть при insufficient_evidence.
Потім Ollama вимикається: AI_OFF має показати unavailable, а незалежний
інцидент повинен знову дати резерв, нові firing/resolved і відновлення.

`results/checks/latest-pr07.json` визначає каталог запуску. Знімки, сирі
відповіді та analysis.json з digest моделі, версією Ollama і часом запиту
лежать у `results/checks/<run_id>/incidents/<incident_id>/`.
`latest-incident.txt` містить ID знімка контрольованої відмови.
Ці runtime-дані та ваги не додаються до Git. Автоматичний протокол для
Git створює тест у `docs/reports/pr07.md`.

## Зіставлення відповіді моделі з доказами виконаного запуску

Запуск `a12641d3b9964d12bdd7b035792c157d`: Ollama 0.40.13, модель
qwen3:0.6b, digest
`7df6b6e09427a769808717c0a93cadc4ae99ed4eb8bf5ca557c90846becea435`.
Реальні запити normal, incident та limited тривали відповідно 8,757 с,
9,211 с та 2,956 с. Сирі відповіді мають done=true і done_reason=stop.
Це підтверджує виконання inference, але не правильність діагнозу.

| Знімок | Факти з evidence.json | Оцінка тверджень моделі |
|---|---|---|
| normal, `4c996e6bbbc642d2b18273ee58dd014c` | E1: обидві HTTP-проби 1; E2: попередній інцидент уже resolved; E3 порожній | Припущення про поточну HTTP-відмову не випливає зі свіжих проб. DNS і кабель не вимірювалися; ці причини не підтверджені. Старе firing не є поточною відмовою. |
| incident, `528cc6151b274c2ab411a3ea36687df4` | E1: primary=0, gateway=1; E2: нове firing; E3: останні HTTP 200 до зупинки | Контрольована дія тесту — stop backend-a. Висновок про проблему primary узгоджується з пробою; insufficient_evidence доречний щодо невідомої моделі першопричини. URL у probable_causes є адресами цілей, а не причинами. Старі HTTP 200 не доводять працездатності в момент знімка. |
| limited, `ba45702868644010af7c9f84a73525c8` | Є лише E1 із повідомленням про проблему, вимірювань немає | insufficient_evidence, порожній список причин і посилання тільки на E1 коректні. Рекомендації перевірити журнали й порт є наступними перевірками, не виконаними діями. |

Для з'ясування причини потрібні стан контейнера backend-a, журнал
зупинки та нова HTTP-проба з явно вказаними джерелом, ціллю й часом.
Сам HTTP-failure не доводить VLAN/DNS/кабельну несправність.

AI_OFF зафіксував unavailable, після чого ALARM_WITHOUT_AI отримав
backend-b, нові firing/resolved цього другого інциденту та повернення
backend-a без Ollama. У всіх analysis.json executed_actions порожній.
Модель не керувала резервом або сповіщеннями.

Після завершення зупиніть стенд, зберігши модель у named volume:

```sh
sh tests/compose.sh pr07 --profile monitoring --profile ai stop
```
