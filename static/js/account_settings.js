// Account settings page functionality

document.addEventListener('DOMContentLoaded', function () {
    // Initialize Bootstrap-select for the preferred_languages field
    var preferredLanguagesSelect = document.getElementById('lang_form-preferred_languages');
    if (preferredLanguagesSelect) {
        if (typeof $(preferredLanguagesSelect).selectpicker === 'function') {
            $(preferredLanguagesSelect).selectpicker();
        } else {
            console.warn('Bootstrap-select library not loaded or selectpicker function not found.');
        }
    }

    // Handle toggle switches
    function handleToggle(toggleId, settingKey) {
        const toggle = document.getElementById(toggleId);
        if (toggle) {
            toggle.addEventListener('change', function() {
                const csrfToken = document.querySelector('input[name="csrf_token"]')?.value;
                const accountUrl = this.getAttribute('data-account-url');
                const successMsg = this.getAttribute('data-success-msg');
                const errorMsg = this.getAttribute('data-error-msg');
                const errorGeneral = this.getAttribute('data-error-general');
                const toggleElement = this;
                
                if (!csrfToken) {
                    console.error('CSRF token not found');
                    showToast('Error: Security token not found', 'danger');
                    this.checked = !this.checked;
                    return;
                }
                
                fetch(accountUrl, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': csrfToken
                    },
                    body: JSON.stringify({ [settingKey]: toggleElement.checked })
                })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        showToast(successMsg || 'Setting updated successfully', 'success');
                    } else {
                        showToast(errorMsg || 'Failed to update setting', 'danger');
                        toggleElement.checked = !toggleElement.checked;
                    }
                })
                .catch(error => {
                    console.error('Error:', error);
                    showToast(errorGeneral || 'Error updating setting', 'danger');
                    toggleElement.checked = !toggleElement.checked;
                });
            });
        }
    }
    
    handleToggle('show_no_subtitles', 'show_no_subtitles');
    handleToggle('prioritize_ass_subtitles', 'prioritize_ass_subtitles');
});
