---
id: netlab-git-guide
type: project-guide
discipline: proektuvannia-avtonomykh-merezh
status: draft
version: 5
updated: '2026-10-31'
sources: []
---

# Власна копія шаблону: fork/import → clone → commit → push

Git зберігає історію локально, GitLab/GitHub — віддалену копію. Fork створює вашу віддалену копію проєкту в межах GitLab. Clone завантажує репозиторій на комп’ютер. Це дві різні дії. Основний початок ПР3 — власна віддалена копія шаблону, а не порожній репозиторій і git init. Усі наступні роботи продовжують цю саму копію.

## 1. GitLab: fork шаблону

1. Увійдіть у свій GitLab. Відкрийте **URL студентського шаблону, наданий викладачем**. Це має бути сторінка проєкту з файлами `README.md`, `docs/` і `tests/`, а не профіль користувача.
2. На сторінці шаблону натисніть Fork. Виберіть власний namespace — простір імен, тобто ваш обліковий запис або доступну вам групу — і назву, наприклад network-lab. Створіть fork і дочекайтеся завершення.
3. Перевірте власника в URL: це має бути ваш namespace. У Code/Clone скопіюйте **HTTPS URL власного fork**.
4. Не створюйте нову порожню копію на кожну ПР. ПР3–7 — п’ять версій одного проєкту.

Офіційне пояснення: [GitLab forks](https://docs.gitlab.com/user/project/repository/forking_workflow/).

## 2. GitHub: імпорт того самого шаблону

Якщо хочете здавати в GitHub, зробіть Import repository: у меню + виберіть Import repository, вставте отриманий URL відкритого студентського GitLab-шаблону, виберіть власника й назву, почніть імпорт. Після завершення відкрийте **свій** GitHub-репозиторій і скопіюйте його HTTPS URL через Code.

Це імпорт, а не міжплатформний fork. Для відкритого шаблону не потрібно передавати GitHub токен викладача. Якщо імпорт недоступний, повідомте викладачу текст помилки доступу. [GitHub Importer](https://docs.github.com/en/migrations/importing-source-code/using-github-importer/importing-a-repository-with-github-importer).

## 3. Клонування на комп’ютер

Відкрийте Bash у навчальному середовищі: Ubuntu WSL для основного Windows-маршруту, Terminal на Mac або термінал обраної Linux/VM. Перейдіть у каталог, де зберігаєте навчальні проєкти. Приклад нижче має **позначення для заміни**, його не слід вводити буквально:

```bash
git clone ВАШ_HTTPS_URL network-lab
cd network-lab
git remote -v
git status
ls -a
```

У першій команді замініть ВАШ_HTTPS_URL скопійованим URL **власного** fork/import. Приклад форми адреси: https://gitlab.com/STUDENT/PROJECT.git або https://github.com/STUDENT/PROJECT.git. STUDENT і PROJECT — приклади, не готові робочі URL. network-lab — довільна локальна назва каталогу; збережіть її місце до кінця курсу.

Очікується `Cloning into ...`, назва поточної гілки та `clean working tree`, файли docs/, tests/, Dockerfile, compose.yaml та прихований .git. Наявність TODO — очікуваний початковий стан. origin у git remote -v має вказувати на ваш fork/import. **Не виконуйте git init і не додавайте origin повторно:** clone уже зробив це.

Якщо ви випадково клонували викладацький URL, спочатку створіть власний fork/import, потім замініть origin командою `git remote set-url origin ВАШ_HTTPS_URL` та перевірте remote -v. Перед push переконайтеся, що власник правильний. У викладацький шаблон студентське рішення не надсилається.

## 4. Локальні дані автора

У вже клонованому каталозі налаштуйте підпис своїх commit:

```bash
git config user.name "Ваше ім’я та прізвище"
git config user.email "ваша-адреса@example.com"
git config --get user.name
git config --get user.email
```

Замініть приклади своїми значеннями; можна взяти privacy email свого Git-сервісу. Без --global налаштування діють лише тут. Це підпис commit, а не авторизація. Очікується, що останні дві команди покажуть введені дані. `not in a git directory` означає неправильний каталог: перевірте pwd і .git. [Git setup](https://git-scm.com/book/en/v2/Getting-Started-First-Time-Git-Setup).

## 5. Фіксація і надсилання кожної роботи

Спочатку заповніть конфігурації за протоколом, виконайте повний tests/check.sh і відкрийте згенерований report.md. Потім виконайте блок commit/tag із вашої ПР. Приклад для ПР3:

```bash
git status --short
git add .
git diff --cached --stat
git commit -m "pr03: configure container environment"
git tag pr03
git rev-parse HEAD
git push -u origin HEAD
git push origin pr03
```

Це пояснення операцій; якщо commit/tag уже виконані блоком ПР3, повторно їх не створюйте.

| Команда | Дія та очікування |
|---|---|
| status --short | Перелік ваших змін після clone; .env, results/, ваг і секретів у ньому немає |
| add . | Готує поточні файли до commit; ще не надсилає їх |
| diff --cached --stat | Показує підготовлені файли. Перевірте склад перед фіксацією |
| commit | Створює версію історії з повідомленням; надрукує короткий SHA |
| tag pr03 | Позначає конкретний commit як зданий етап |
| rev-parse HEAD | Повний commit SHA для перевірки версії; окремо здавати його не потрібно |
| push -u origin HEAD | Надсилає поточну гілку й запам’ятовує зв’язок із remote |
| push origin pr03 | Окремо надсилає тег; на сайті з’являється pr03 |

### Що саме потрапить у commit ПР3

Припустімо, ви заповнили Dockerfile, виконали add, а потім виправили WORKDIR. У підготовленому стані може бути перший варіант, хоча редактор уже показує другий. Перед commit звірте `git status`, `git diff` та `git diff --cached`: перша різниця показує непідготовлені зміни відстежуваних файлів, друга — підготовлені. Повторний add потрібного файла включить його поточний вміст. `--stat` показує склад і розмір змін, а повна cached-різниця дозволяє прочитати рядки. Це спосіб перевірити вже потрібний commit, не новий оцінюваний крок.

Перед push перевірте фактичну гілку через `git branch --show-current`. `HEAD` у команді push позначає поточну гілку; її назва має бути непорожньою. Назва `main` не є вимогою Git або цієї роботи. Commit зберігається локально, push гілки й push тега є різними діями. Метадані автора не замінюють автентифікації.

Правила .gitignore не вилучають автоматично файл, який уже відстежується. Тому cached-різницю читають навіть тоді, коли ignore існує: .env, секрети та results не повинні потрапити до підготовленого вмісту. Повідомлення Author identity unknown означає, що commit ще не створено; nothing to commit перевіряють разом зі status, а не лікують випадковою зміною тексту повідомлення.

Для ПР4–7 повторюйте ті самі дії з номером роботи. Виправлення — новий commit і тег prNN-v2. Не пересувайте вже здані теги й не використовуйте force push. `nothing to commit` означає відсутність нових підготовлених змін; `tag already exists` — уже наявний тег.

Якщо HTTPS потребує входу, використайте credential manager/вхід у браузері або токен за офіційним маршрутом сервісу. Не вставляйте пароль/токен у URL, конфігурації чи звіт. [GitHub authentication](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/about-authentication-to-github), [GitLab tokens](https://docs.gitlab.com/user/profile/personal_access_tokens/). Authentication failed означає проблему доступу, а не Docker. При non-fast-forward спершу розберіться з історією; не стирайте її force push.

Тест автоматично зберігає Markdown у docs/reports/prNN.md (NN — номер роботи). Додайте його до commit разом із конфігураціями й надішліть гілку та тег. Здайте тільки URL власного репозиторію: викладач перегляне файли й протокол там. Окремі вкладення, SHA та URL pipeline не потрібні. results/ не комітиться. Усі ПР оцінюються автоматично: ПР3–6 по 10, ПР7 12. Платформа не впливає на бал. .gitlab-ci.yml працює лише на GitLab із налаштованим Docker runner; його відсутність на GitHub не заважає локальній перевірці. Локальний звіт є самоперевіркою. Офіційний автоматичний результат визначається перевіркою зданої версії, яку контролює викладач.
