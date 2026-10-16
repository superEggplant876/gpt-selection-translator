"""Keep account-provided model identifiers dynamic, without version guesses."""
REFRESH_SECONDS = 6 * 60 * 60


def visible_models(data):
    result, seen = [], set()
    for item in data.get('models', []):
        slug = item.get('slug')
        if item.get('visibility') != 'list' or not isinstance(slug, str) or not slug or slug in seen:
            continue
        seen.add(slug)
        result.append({'slug': slug, 'display_name': item.get('display_name') or slug})
    return result


def choose_model(models, current='', automatic=True):
    if not models:
        raise ValueError('Empty model catalog')
    if automatic:
        return 0
    return next((i for i, item in enumerate(models) if item['slug'] == current), 0)
