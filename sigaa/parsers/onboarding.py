"""Value-free metadata from SIGAA pages."""
import re
from bs4 import BeautifulSoup


def sigaa_version(text):
    soup = BeautifulSoup(text, "lxml")
    footer = soup.select_one("#rodape, #footer, footer")
    match = re.search(r"(?:v|vers[aã]o\s*)([0-9]+(?:\.[0-9]+)+(?:[-.][a-zA-Z0-9]+)*)",
                      footer.get_text(" ", strip=True) if footer else "", re.I)
    return match.group(1) if match else None


def login_forms(html):
    soup = BeautifulSoup(html, "lxml")
    forms = []
    for form in soup.select("form"):
        fields = [str(node.get("name")) for node in form.select("input[name]")]
        action = str(form.get("action", ""))
        strategy = None
        if {"form:login", "form:senha"}.issubset(fields):
            strategy = "jsf-logon"
        elif form.select_one('input[type="password"]') and "logar.do" in action:
            strategy = "classic-struts"
        forms.append({"action": action, "fields": fields, "strategy": strategy})
    return forms


def form_secret_values(html):
    """Extract sensitive form values for the private-data scanner."""
    selector = 'input[name="javax.faces.ViewState"], input[type="password"]'
    return [str(node.get("value", ""))
            for node in BeautifulSoup(html, "html.parser").select(selector)]
