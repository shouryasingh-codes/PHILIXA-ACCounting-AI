"""
Empirical Stress Test for Milestone 5: Frontend RBAC Gating, Selectors, and DOM Attributes
Conducted by Challenger M5 (Iteration 2) using Python standard library (html.parser).
"""
import re
from html.parser import HTMLParser
from pathlib import Path
import pytest

APP_ROOT = Path(__file__).resolve().parent.parent.parent
INDEX_HTML = APP_ROOT / "app" / "web" / "index.html"
APP_JS = APP_ROOT / "app" / "web" / "app.js"
VOICE_JS = APP_ROOT / "app" / "web" / "philixa-voice.js"


class SimpleHTMLDOMParser(HTMLParser):
    """Parses HTML into a lightweight DOM structure."""
    def __init__(self):
        super().__init__()
        self.elements_by_id = {}
        self.gated_elements = []

    def handle_starttag(self, tag, attrs):
        attr_dict = dict(attrs)
        el_id = attr_dict.get("id")
        classes = attr_dict.get("class", "").split()
        dataset = {}
        for k, v in attr_dict.items():
            if k == "data-min-role":
                dataset["minRole"] = v
            elif k == "data-rbac":
                dataset["rbac"] = v

        elem_obj = {
            "tag": tag,
            "id": el_id,
            "classes": set(classes),
            "attrs": attr_dict,
            "dataset": dataset,
        }

        if el_id:
            self.elements_by_id[el_id] = elem_obj

        if "minRole" in dataset or "rbac" in dataset:
            self.gated_elements.append(elem_obj)


class TestM5StaticAndAttributeIntegrity:
    """Verify HTML structure and attribute decorations for RBAC."""

    @pytest.fixture(autouse=True)
    def load_files(self):
        assert INDEX_HTML.exists(), f"Missing {INDEX_HTML}"
        assert APP_JS.exists(), f"Missing {APP_JS}"
        self.html_content = INDEX_HTML.read_text(encoding="utf-8")
        self.js_content = APP_JS.read_text(encoding="utf-8")
        
        self.parser = SimpleHTMLDOMParser()
        self.parser.feed(self.html_content)

    def test_manage_members_btn_has_data_min_role_admin(self):
        """#manageMembersBtn must exist and have data-min-role='admin'."""
        btn = self.parser.elements_by_id.get("manageMembersBtn")
        assert btn is not None, "#manageMembersBtn element not found in index.html"
        assert btn["dataset"].get("minRole") == "admin", (
            f"#manageMembersBtn data-min-role expected 'admin', got '{btn['dataset'].get('minRole')}'"
        )

    def test_invite_section_has_data_min_role_admin(self):
        """#inviteSection must exist and have data-min-role='admin'."""
        invite_sec = self.parser.elements_by_id.get("inviteSection")
        assert invite_sec is not None, "#inviteSection element not found in index.html"
        assert invite_sec["dataset"].get("minRole") == "admin", (
            f"#inviteSection data-min-role expected 'admin', got '{invite_sec['dataset'].get('minRole')}'"
        )

    def test_apply_role_permissions_selector_and_dataset(self):
        """applyRolePermissions must query [data-rbac], [data-min-role] and read minRole || rbac."""
        assert 'document.querySelectorAll("[data-rbac], [data-min-role]")' in self.js_content, (
            "applyRolePermissions() does not query both [data-rbac] and [data-min-role]"
        )
        assert "el.dataset.minRole || el.dataset.rbac" in self.js_content, (
            "applyRolePermissions() does not check both el.dataset.minRole and el.dataset.rbac"
        )

    def test_forbidden_legacy_strings_purged(self):
        """Forbidden API keys and legacy constants must not appear in web assets."""
        forbidden = [
            "X-API-Key",
            "api_key=",
            "DEMO_API_KEY",
            '"org_1"',
            '"SYSTEM"',
            '"philixa-demo-secret-123"',
        ]
        for f in forbidden:
            assert f not in self.html_content, f"Forbidden string '{f}' found in index.html"
            assert f not in self.js_content, f"Forbidden string '{f}' found in app.js"


class DOMElement:
    """Mock DOM Element representing HTML element with classList, style, and dataset."""
    def __init__(self, id=None, tag="div", class_list=None, style=None, dataset=None):
        self.id = id
        self.tag = tag
        self.classList = set(class_list or [])
        self.style = style or {"display": ""}
        self.dataset = dataset or {}
        self.textContent = ""
        self.className = ""

    def add_class(self, cls):
        self.classList.add(cls)

    def remove_class(self, cls):
        self.classList.discard(cls)

    @property
    def is_visible(self):
        return "hidden" not in self.classList and self.style.get("display") != "none"


class MockAppDOM:
    """Simulation harness for app.js DOM state and applyRolePermissions()."""
    def __init__(self, parser: SimpleHTMLDOMParser):
        self.elements = []
        self.els = {}
        self.init_from_parser(parser)

    def init_from_parser(self, parser: SimpleHTMLDOMParser):
        for raw in parser.gated_elements:
            dom_el = DOMElement(
                id=raw["id"],
                tag=raw["tag"],
                class_list=raw["classes"],
                dataset=dict(raw["dataset"])
            )
            self.elements.append(dom_el)
            if raw["id"]:
                self.els[raw["id"]] = dom_el

        # Track manageMembersBtn and activeRoleBadge if present
        if "manageMembersBtn" in parser.elements_by_id and "manageMembersBtn" not in self.els:
            raw = parser.elements_by_id["manageMembersBtn"]
            dom_el = DOMElement(
                id="manageMembersBtn",
                tag=raw["tag"],
                class_list=raw["classes"],
                dataset=dict(raw["dataset"])
            )
            self.elements.append(dom_el)
            self.els["manageMembersBtn"] = dom_el

        if "activeRoleBadge" in parser.elements_by_id:
            raw = parser.elements_by_id["activeRoleBadge"]
            self.els["activeRoleBadge"] = DOMElement(
                id="activeRoleBadge",
                tag=raw["tag"],
                class_list=raw["classes"]
            )
        else:
            self.els["activeRoleBadge"] = DOMElement(
                id="activeRoleBadge",
                tag="span",
                class_list={"role-badge"}
            )

    def apply_role_permissions(self, auth_role: str):
        """Exact JS mirror of applyRolePermissions() from app.js lines 494-523."""
        role = (auth_role or "member").lower()
        is_owner = role == "owner"
        is_admin = role == "admin" or is_owner

        if "activeRoleBadge" in self.els:
            badge = self.els["activeRoleBadge"]
            badge.textContent = role.upper()
            badge.className = f"role-badge role-{role}"

        # Manage members button: visible only to owner and admin
        if "manageMembersBtn" in self.els:
            if is_admin:
                self.els["manageMembersBtn"].style["display"] = ""
                self.els["manageMembersBtn"].remove_class("hidden")
            else:
                self.els["manageMembersBtn"].style["display"] = "none"
                self.els["manageMembersBtn"].add_class("hidden")

        # Generic data-min-role and data-rbac DOM gating
        for el in self.elements:
            required = (el.dataset.get("minRole") or el.dataset.get("rbac") or "").lower()
            if required == "owner" and not is_owner:
                el.add_class("hidden")
                el.style["display"] = "none"
            elif (required == "admin" or required == "admin-only") and not is_admin:
                el.add_class("hidden")
                el.style["display"] = "none"
            else:
                el.remove_class("hidden")
                el.style["display"] = ""


class TestM5EmpiricalRBACStressExecution:
    """Stress tests running dynamic simulation against actual parsed index.html elements."""

    @pytest.fixture(autouse=True)
    def setup_dom(self):
        html_content = INDEX_HTML.read_text(encoding="utf-8")
        parser = SimpleHTMLDOMParser()
        parser.feed(html_content)
        self.mock_dom = MockAppDOM(parser)

    def test_member_role_hides_all_admin_and_owner_elements(self):
        """When role is 'member', #manageMembersBtn and #inviteSection MUST be hidden."""
        self.mock_dom.apply_role_permissions("member")

        # manageMembersBtn
        btn = self.mock_dom.els.get("manageMembersBtn")
        assert btn is not None
        assert btn.style["display"] == "none", "manageMembersBtn style.display should be 'none' for member"
        assert "hidden" in btn.classList, "manageMembersBtn should have 'hidden' class for member"
        assert not btn.is_visible

        # inviteSection
        invite = self.mock_dom.els.get("inviteSection")
        assert invite is not None
        assert invite.style["display"] == "none", "inviteSection style.display should be 'none' for member"
        assert "hidden" in invite.classList, "inviteSection should have 'hidden' class for member"
        assert not invite.is_visible

        # activeRoleBadge
        badge = self.mock_dom.els.get("activeRoleBadge")
        assert badge.textContent == "MEMBER"
        assert badge.className == "role-badge role-member"

    def test_admin_role_shows_admin_elements_hides_owner_elements(self):
        """When role is 'admin', admin elements are visible while owner-only are hidden."""
        # Inject an owner-only test element
        owner_el = DOMElement(id="ownerSettings", dataset={"minRole": "owner"})
        self.mock_dom.elements.append(owner_el)
        self.mock_dom.els["ownerSettings"] = owner_el

        self.mock_dom.apply_role_permissions("admin")

        btn = self.mock_dom.els.get("manageMembersBtn")
        assert btn.style["display"] == ""
        assert "hidden" not in btn.classList
        assert btn.is_visible

        invite = self.mock_dom.els.get("inviteSection")
        assert invite.style["display"] == ""
        assert "hidden" not in invite.classList
        assert invite.is_visible

        assert not owner_el.is_visible
        assert owner_el.style["display"] == "none"
        assert "hidden" in owner_el.classList

        badge = self.mock_dom.els.get("activeRoleBadge")
        assert badge.textContent == "ADMIN"
        assert badge.className == "role-badge role-admin"

    def test_owner_role_shows_all_elements(self):
        """When role is 'owner', all gated elements (admin + owner) are visible."""
        owner_el = DOMElement(id="ownerSettings", dataset={"minRole": "owner"})
        self.mock_dom.elements.append(owner_el)
        self.mock_dom.els["ownerSettings"] = owner_el

        self.mock_dom.apply_role_permissions("owner")

        btn = self.mock_dom.els.get("manageMembersBtn")
        assert btn.is_visible
        invite = self.mock_dom.els.get("inviteSection")
        assert invite.is_visible
        assert owner_el.is_visible

        badge = self.mock_dom.els.get("activeRoleBadge")
        assert badge.textContent == "OWNER"
        assert badge.className == "role-badge role-owner"

    @pytest.mark.parametrize("input_role,expected_effective", [
        ("MEMBER", "member"),
        ("Admin", "admin"),
        ("OWNER", "owner"),
        (None, "member"),
        ("", "member"),
        ("guest", "guest"),
    ])
    def test_role_case_insensitivity_and_defaults(self, input_role, expected_effective):
        """Roles should be case-insensitive and default to 'member'."""
        self.mock_dom.apply_role_permissions(input_role)
        badge = self.mock_dom.els.get("activeRoleBadge")
        assert badge.textContent == expected_effective.upper()
        assert badge.className == f"role-badge role-{expected_effective}"

        btn = self.mock_dom.els.get("manageMembersBtn")
        if expected_effective in ("admin", "owner"):
            assert btn.is_visible
        else:
            assert not btn.is_visible

    def test_attribute_precedence_and_backward_compatibility(self):
        """data-min-role takes precedence over data-rbac if both present."""
        hybrid_el = DOMElement(id="hybrid", dataset={"minRole": "owner", "rbac": "admin"})
        self.mock_dom.elements.append(hybrid_el)

        # For admin: minRole is owner, so should be hidden even though rbac was admin
        self.mock_dom.apply_role_permissions("admin")
        assert not hybrid_el.is_visible
        assert "hidden" in hybrid_el.classList

        # For owner: visible
        self.mock_dom.apply_role_permissions("owner")
        assert hybrid_el.is_visible
        assert "hidden" not in hybrid_el.classList

    def test_legacy_data_rbac_admin_only_attribute(self):
        """data-rbac='admin-only' is supported for backward compatibility."""
        legacy_el = DOMElement(id="legacy", dataset={"rbac": "admin-only"})
        self.mock_dom.elements.append(legacy_el)

        self.mock_dom.apply_role_permissions("member")
        assert not legacy_el.is_visible

        self.mock_dom.apply_role_permissions("admin")
        assert legacy_el.is_visible

        self.mock_dom.apply_role_permissions("owner")
        assert legacy_el.is_visible
