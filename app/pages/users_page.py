"""
Users page — admin-only desktop user management.

Shows every rwa_users row for the current society, with role-edit,
password-reset, enable/disable, and add-new. Refuses to demote /
disable the last active admin so a society can't lock itself out.

Audit log entries are written for: add_user, update_user,
disable_user, reset_password.
"""
from __future__ import annotations

from PySide6.QtCore    import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QTableWidget, QTableWidgetItem, QDialog, QFormLayout, QComboBox,
    QMessageBox, QFrame,
)

from app.theme    import THEME
from app.services.auth import (
    UserService, VALID_ROLES, AuthSession,
    SEED_ADMIN_USERNAME, SEED_ADMIN_PASSWORD,
)
from app.services.audit import AuditLogService
from app.pages._common  import style_table, apply_text_filter


class _UserDialog(QDialog):
    """Add / edit a user. On edit, password field stays blank and is
    only updated if the admin fills it in (saves a click in the
    common 'change role only' case)."""

    saved = Signal()

    def __init__(self, svc: UserService,
                 user_id: int | None = None,
                 parent=None):
        super().__init__(parent)
        self.svc = svc
        self.uid = user_id
        self._existing = svc.get(user_id) if user_id else None

        self.setWindowTitle("Edit user" if user_id else "Add user")
        self.setMinimumWidth(440)
        self.setModal(True)

        v = QVBoxLayout(self); v.setSpacing(10)
        v.setContentsMargins(20, 20, 20, 20)

        hdr = QLabel("✎ Edit user" if self._existing else "+ Add user")
        hdr.setStyleSheet(
            f"font-size:14px; font-weight:bold; color:{THEME['accent']};"
        )
        v.addWidget(hdr)

        form = QFormLayout(); form.setSpacing(8)
        e = self._existing or {}

        self.username = QLineEdit(e.get("username") or "")
        self.username.setFixedHeight(30)
        if self._existing:
            self.username.setReadOnly(True)
        form.addRow(QLabel("Username *"), self.username)

        self.password = QLineEdit()
        self.password.setFixedHeight(30)
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setPlaceholderText(
            "(leave blank to keep current)" if self._existing else "min 4 chars"
        )
        form.addRow(QLabel("Password " + ("" if self._existing else "*")),
                    self.password)

        self.role = QComboBox(); self.role.setFixedHeight(30)
        for r in VALID_ROLES:
            self.role.addItem(r.title(), r)
        cur_role = e.get("role") or "secretary"
        for i in range(self.role.count()):
            if self.role.itemData(i) == cur_role:
                self.role.setCurrentIndex(i); break
        form.addRow(QLabel("Role *"), self.role)

        self.full_name = QLineEdit(e.get("full_name") or "")
        self.full_name.setFixedHeight(30)
        form.addRow(QLabel("Full name"), self.full_name)

        self.email = QLineEdit(e.get("email") or "")
        self.email.setFixedHeight(30)
        form.addRow(QLabel("Email"), self.email)

        v.addLayout(form)

        roles_note = QLabel(
            "<b>admin</b> manages users + sees audit log. "
            "<b>treasurer</b> handles members + financial broadcasts. "
            "<b>secretary</b> handles notices, complaints, polls, "
            "broadcasts, visitor passes. <b>auditor</b> is read-only "
            "across the app."
        )
        roles_note.setWordWrap(True)
        roles_note.setStyleSheet(
            f"color:{THEME['text_secondary']}; font-size:10px;"
            f" background:{THEME.get('bg_hover','#334155')};"
            f" padding:8px; border-radius:6px;"
        )
        v.addWidget(roles_note)

        row = QHBoxLayout(); row.addStretch()
        cancel = QPushButton("Cancel"); cancel.clicked.connect(self.reject)
        save   = QPushButton("Save"); save.setObjectName("btn_primary")
        save.clicked.connect(self._save)
        row.addWidget(cancel); row.addWidget(save)
        v.addLayout(row)

    def _save(self) -> None:
        for w in (self.username, self.password, self.full_name, self.email):
            w.clearFocus()

        try:
            if self._existing:
                new_role = self.role.currentData()
                # Last-admin guard: refuse to demote the last active admin.
                if (self._existing["role"] == "admin"
                        and new_role != "admin"
                        and self.svc.count_active_admins() <= 1):
                    raise ValueError(
                        "Can't demote the last active admin — promote "
                        "someone else to admin first."
                    )
                self.svc.update(
                    self.uid,
                    role=new_role,
                    full_name=self.full_name.text().strip(),
                    email=self.email.text().strip(),
                )
                if self.password.text():
                    self.svc.set_password(self.uid, self.password.text())
            else:
                self.svc.add(
                    username=self.username.text(),
                    password=self.password.text(),
                    role=self.role.currentData(),
                    full_name=self.full_name.text().strip(),
                    email=self.email.text().strip(),
                )
        except ValueError as e:
            QMessageBox.warning(self, "Cannot save", str(e))
            return

        self.saved.emit()
        self.accept()


class UsersPage(QWidget):
    """Admin-only. Non-admins see a placeholder instead."""

    def __init__(self, db, company_id: int, tree,
                 auth: AuthSession, parent=None):
        super().__init__(parent)
        self.db = db
        self.company_id = company_id
        self.auth  = auth
        self.svc   = UserService(db, company_id)
        self.audit = AuditLogService(db, company_id)
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 16, 24, 24); layout.setSpacing(10)

        title = QLabel("Users")
        title.setObjectName("page_title")
        layout.addWidget(title)

        sub = QLabel(
            "Committee members who can sign in to RWAGenie for this "
            "society. Each user has a role that controls which pages "
            "and actions they see."
        )
        sub.setObjectName("page_subtitle")
        layout.addWidget(sub)

        self.seed_warning = QLabel("")
        self.seed_warning.setWordWrap(True)
        self.seed_warning.setStyleSheet(
            f"color:{THEME['warning']}; font-size:11px;"
            f" background:{THEME.get('bg_hover','#334155')};"
            f" padding:8px; border-radius:6px;"
        )
        self.seed_warning.hide()
        layout.addWidget(self.seed_warning)

        bar = QFrame(); bar.setObjectName("card")
        bar_l = QHBoxLayout(bar)
        bar_l.setContentsMargins(10, 6, 10, 6); bar_l.setSpacing(8)

        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("🔍 Filter…")
        self.filter_edit.setFixedHeight(30)
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.textChanged.connect(
            lambda t: apply_text_filter(self.table, t)
        )
        bar_l.addWidget(self.filter_edit, 3)

        add = QPushButton("+ Add user"); add.setObjectName("btn_primary")
        add.setFixedHeight(30); add.clicked.connect(self._on_add)
        bar_l.addWidget(add)

        edit = QPushButton("Edit"); edit.setFixedHeight(30)
        edit.clicked.connect(self._on_edit)
        bar_l.addWidget(edit)

        toggle = QPushButton("Enable / Disable"); toggle.setFixedHeight(30)
        toggle.clicked.connect(self._on_toggle_active)
        bar_l.addWidget(toggle)

        layout.addWidget(bar)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["Username", "Role", "Full name", "Email", "Last login", "Active"]
        )
        style_table(self.table, stretch_cols=[2, 3])
        self.table.doubleClicked.connect(self._on_edit)
        layout.addWidget(self.table, 1)

        self.summary = QLabel("")
        self.summary.setStyleSheet(
            f"color:{THEME['text_secondary']}; font-size:11px; padding:4px;"
        )
        layout.addWidget(self.summary)

    def refresh(self):
        users = self.svc.list()
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(users))
        for r, u in enumerate(users):
            uname = QTableWidgetItem(u["username"])
            uname.setData(Qt.ItemDataRole.UserRole, u["id"])
            self.table.setItem(r, 0, uname)
            self.table.setItem(r, 1, QTableWidgetItem((u["role"] or "").title()))
            self.table.setItem(r, 2, QTableWidgetItem(u.get("full_name") or ""))
            self.table.setItem(r, 3, QTableWidgetItem(u.get("email") or ""))
            self.table.setItem(r, 4, QTableWidgetItem(u.get("last_login_at") or "—"))
            self.table.setItem(r, 5, QTableWidgetItem("Yes" if u["active"] else "No"))
        self.table.setSortingEnabled(True)
        apply_text_filter(self.table, self.filter_edit.text())

        actives = sum(1 for u in users if u["active"])
        admins  = sum(1 for u in users if u["active"] and u["role"] == "admin")
        self.summary.setText(
            f"{len(users)} user(s)  ·  {actives} active  ·  {admins} admin"
        )

        # Default-creds nag: if the seed admin/admin still works, warn.
        if self.svc.authenticate(SEED_ADMIN_USERNAME, SEED_ADMIN_PASSWORD):
            self.seed_warning.setText(
                f"⚠ The default <b>{SEED_ADMIN_USERNAME}/{SEED_ADMIN_PASSWORD}</b> "
                "login still works. Edit the admin user and set a real password."
            )
            self.seed_warning.show()
        else:
            self.seed_warning.hide()

    def _selected_uid(self) -> int | None:
        row = self.table.currentRow()
        if row < 0: return None
        item = self.table.item(row, 0)
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    # ── Actions ────────────────────────────────────────────────────────

    def _on_add(self):
        dlg = _UserDialog(self.svc, parent=self)
        dlg.saved.connect(lambda: (self.refresh(), self._audit_after_add(dlg)))
        dlg.exec()

    def _audit_after_add(self, dlg: _UserDialog) -> None:
        # Find the row that was just created (most recent matching uname)
        for u in self.svc.list():
            if u["username"] == dlg.username.text().strip():
                self.audit.record(
                    self.auth, action="add_user",
                    entity_type="user", entity_id=u["id"],
                    summary=f"{u['username']} ({u['role']})",
                    after={"username": u["username"], "role": u["role"]},
                )
                return

    def _on_edit(self, *_):
        uid = self._selected_uid()
        if not uid:
            QMessageBox.information(self, "Pick a user",
                                    "Select a row, then click Edit.")
            return
        before = self.svc.get(uid)
        dlg = _UserDialog(self.svc, user_id=uid, parent=self)

        def _on_saved():
            after = self.svc.get(uid)
            changed = {
                k: (before.get(k), after.get(k))
                for k in ("role", "full_name", "email", "active")
                if before.get(k) != after.get(k)
            }
            pwd_changed = bool(dlg.password.text())
            if pwd_changed:
                changed["password"] = ("***", "***")  # don't log values
            self.audit.record(
                self.auth, action="update_user",
                entity_type="user", entity_id=uid,
                summary=after["username"],
                before={k: v[0] for k, v in changed.items()},
                after={k: v[1] for k, v in changed.items()},
            )
            self.refresh()

        dlg.saved.connect(_on_saved)
        dlg.exec()

    def _on_toggle_active(self):
        uid = self._selected_uid()
        if not uid:
            return
        u = self.svc.get(uid)
        if not u: return
        will_disable = bool(u["active"])
        # Last-admin guard
        if will_disable and u["role"] == "admin" and self.svc.count_active_admins() <= 1:
            QMessageBox.warning(
                self, "Refused",
                "Can't disable the last active admin — promote someone "
                "else to admin first.",
            )
            return
        verb = "Disable" if will_disable else "Enable"
        if QMessageBox.question(
            self, verb,
            f"{verb} user '{u['username']}'?",
        ) != QMessageBox.StandardButton.Yes:
            return

        if will_disable:
            self.svc.delete(uid)
            action = "disable_user"
        else:
            self.svc.update(uid, active=True)
            action = "enable_user"
        self.audit.record(
            self.auth, action=action,
            entity_type="user", entity_id=uid,
            summary=u["username"],
        )
        self.refresh()
