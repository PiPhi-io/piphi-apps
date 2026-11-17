#!/bin/sh

identity_transaction_active=0
identity_had_password=0
identity_had_acl=0

identity_rollback() {
  [ "$identity_transaction_active" -eq 1 ] || return 0
  if [ "$identity_had_password" -eq 1 ]; then
    mv -f "${password_file}.previous" "$password_file" || return 1
  else
    rm -f "$password_file" || return 1
  fi
  if [ "$identity_had_acl" -eq 1 ]; then
    mv -f "${acl_file}.previous" "$acl_file" || return 1
  else
    rm -f "$acl_file" || return 1
  fi
  identity_transaction_active=0
}

identity_install_candidates() {
  identity_had_password=0
  identity_had_acl=0
  if [ -f "$password_file" ]; then cp -p "$password_file" "${password_file}.previous" || return 1; identity_had_password=1; fi
  if [ -f "$acl_file" ]; then cp -p "$acl_file" "${acl_file}.previous" || return 1; identity_had_acl=1; fi
  identity_transaction_active=1

  if ! mv -f "$password_candidate" "$password_file"; then identity_rollback; return 1; fi
  if [ "${PIPHI_TEST_FAIL_IDENTITY_STEP:-}" = "after-password-install" ]; then identity_rollback; return 1; fi
  if ! mv -f "$acl_candidate" "$acl_file"; then identity_rollback; return 1; fi
  if [ "${PIPHI_TEST_FAIL_IDENTITY_STEP:-}" = "after-acl-install" ]; then identity_rollback; return 1; fi
  return 0
}

identity_commit() {
  [ "$identity_transaction_active" -eq 1 ] || return 1
  identity_transaction_active=0
  rm -f "${password_file}.previous" "${acl_file}.previous"
}

identity_cleanup() {
  if [ "$identity_transaction_active" -eq 1 ]; then identity_rollback || true; fi
  rm -f "$password_candidate" "$acl_candidate"
  if [ "$identity_transaction_active" -eq 0 ]; then rm -f "${password_file}.previous" "${acl_file}.previous"; fi
}
