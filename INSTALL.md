# Установка ПростоJPG

Сначала установите [расширение ПростоJPG](https://chromewebstore.google.com/detail/простоjpg/djjocjgglhbkcfclclilmamlcoggoole) в Chrome или Яндекс Браузере и скачайте нужные фото через Инструменты Селлера.

Чтобы локальный Codex или Claude Code установил плагин, напишите:

```text
Установи https://github.com/8976878-source/ProstoJPG/
```

Помощник выполняет команды клиента, в котором вы работаете. Для установки нужен доступ к компьютеру и установленный клиент.

## Codex

```text
codex plugin marketplace add 8976878-source/ProstoJPG
codex plugin add prostojpg@prostojpg-marketplace
```

После установки при необходимости откройте новый чат. Выберите команду на странице плагина или используйте `$prostojpg-1`, `$prostojpg-2`, `$prostojpg-3`.

## Claude Code

```text
claude plugin marketplace add 8976878-source/ProstoJPG
claude plugin install prostojpg@prostojpg-marketplace
```

Команды: `/prostojpg:prostojpg-1`, `/prostojpg:prostojpg-2`, `/prostojpg:prostojpg-3`.

Для создания фото через Claude Code нужен установленный Codex с входом через ChatGPT и доступной генерацией изображений. Если нужен вход, выполните `codex login` через официальное окно авторизации. Дополнительный плагин генератора и API-ключ не нужны.

## Обновление

Повторите команды установки. При необходимости обновите marketplace средствами вашего клиента и откройте новый чат. Не удаляйте чужие навыки.

Установка расширения подтверждается пользователем в браузере. Открытая страница магазина не подтверждает его установку.

[Сайт](https://prosto-seller.ru/) · [Политика](https://prosto-seller.ru/legal)
