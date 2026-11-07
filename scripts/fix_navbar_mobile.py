from pathlib import Path

p = Path(__file__).resolve().parents[1] / "templates" / "partials" / "navbar.html"
text = p.read_text(encoding="utf-8")
text = text.replace("<motion ", "<motion ").replace("</motion>", "</motion>")
text = text.replace("<motion ", "<div ").replace("</motion>", "</div>")
text = text.replace('id="current-time-mobile"', 'class="gm-nav-time"')
text = text.replace('id="current-date-gregorian-mobile"', 'class="gm-nav-date-gregorian"')
text = text.replace('id="current-date-hijri-mobile"', 'class="gm-nav-date-hijri"')
text = text.replace('id="usd-rate-mobile"', 'class="gm-nav-usd-rate"')
text = text.replace('id="jod-rate-mobile"', 'class="gm-nav-jod-rate"')
text = text.replace('data-search="global-mobile"', 'data-search="global"')
text = text.replace('data-search-target="global-mobile"', 'data-search-target="global"')
text = text.replace('name="gm_search_global_mobile"', 'name="gm_search_global_compact"')
text = text.replace("\t\t\t\t{% endfor %}", "            {% endfor %}")

old_shop = """    {% if current_user.is_authenticated and (has_perm('view_shop') or has_perm('manage_shop')) %}
    <li class="nav-item d-none d-lg-block">
      <a class="nav-link nav-strong" href="{{ url_for('shop.catalog') }}" target="_blank" title="المتجر">
        <i class="fas fa-store"></i>
      </a>
    </li>
    {% endif %}"""

new_shop = """    {% if current_user.is_authenticated and (has_perm('view_shop') or has_perm('manage_shop')) %}
    <li class="nav-item d-lg-none">
      <a class="nav-link nav-strong" href="{{ url_for('shop.catalog') }}" target="_blank" title="المتجر">
        <i class="fas fa-store"></i>
      </a>
    </li>
    <li class="nav-item d-none d-lg-block">
      <a class="nav-link nav-strong" href="{{ url_for('shop.catalog') }}" target="_blank" title="المتجر">
        <i class="fas fa-store"></i>
      </a>
    </li>
    {% endif %}"""

if old_shop in text:
    text = text.replace(old_shop, new_shop)

old_ai = """        <li class="nav-item d-none d-lg-block">
          <a class="nav-link nav-strong" href="{{ url_for('ai.assistant') }}" title="المساعد الذكي">
            <i class="fas fa-robot"></i>
          </a>
        </li>"""

new_ai = """        <li class="nav-item d-lg-none">
          <a class="nav-link nav-strong" href="{{ url_for('ai.assistant') }}" title="المساعد الذكي">
            <i class="fas fa-robot"></i>
          </a>
        </li>
        <li class="nav-item d-none d-lg-block">
          <a class="nav-link nav-strong" href="{{ url_for('ai.assistant') }}" title="المساعد الذكي">
            <i class="fas fa-robot"></i>
          </a>
        </li>"""

if old_ai in text:
    text = text.replace(old_ai, new_ai)

p.write_text(text, encoding="utf-8")
print("navbar patched")
