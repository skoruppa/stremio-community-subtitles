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

    // Handle show_no_subtitles toggle
    const showNoSubtitlesToggle = document.getElementById('show_no_subtitles');
    if (showNoSubtitlesToggle) {
        showNoSubtitlesToggle.addEventListener('change', function() {
            const csrfToken = document.querySelector('input[name="csrf_token"]')?.value;
            const accountUrl = this.getAttribute('data-account-url');
            
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
                body: JSON.stringify({ show_no_subtitles: this.checked })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    showToast('Setting updated successfully', 'success');
                } else {
                    showToast('Failed to update setting', 'danger');
                    this.checked = !this.checked;
                }
            })
            .catch(error => {
                console.error('Error:', error);
                showToast('Error updating setting', 'danger');
                this.checked = !this.checked;
            });
        });
    }
});
