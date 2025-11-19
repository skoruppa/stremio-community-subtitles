// Voting functionality for subtitles
function initVoting(csrfToken, voteUrlTemplate) {
    document.querySelectorAll('.vote-btn').forEach(function(btn) {
        btn.addEventListener('click', function(e) {
            this.blur();
            const container = this.closest('[data-subtitle-id]') || this.closest('.list-group-item');
            const subtitleId = container.dataset.subtitleId;
            const voteType = this.dataset.voteType;
            const currentVote = parseInt(container.dataset.currentVote || '0');
            const newVote = voteType === 'up' ? 1 : -1;
            const isRemoved = container.dataset.removed === 'true';
            
            const url = voteUrlTemplate.replace('SUBTITLE_ID', subtitleId).replace('VOTE_TYPE', voteType);
            
            fetch(url, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded',
                    'X-Requested-With': 'XMLHttpRequest'
                },
                body: 'csrf_token=' + csrfToken
            }).then(response => response.json())
            .then(data => {
                const upBtn = container.querySelector('[data-vote-type="up"]');
                const downBtn = container.querySelector('[data-vote-type="down"]');
                
                if (data.removed) {
                    // Vote removed
                    if (container.classList.contains('list-group-item') && container.dataset.voteId) {
                        // In voted-subtitles page
                        container.style.opacity = '0.5';
                        container.dataset.removed = 'true';
                        container.dataset.currentVote = '0';
                    } else {
                        // In my-subtitles page
                        container.dataset.currentVote = '0';
                    }
                    upBtn.className = 'btn btn-sm vote-btn btn-outline-success';
                    downBtn.className = 'btn btn-sm vote-btn btn-outline-danger';
                    upBtn.blur();
                    downBtn.blur();
                    showToast('Vote removed.', 'info');
                } else {
                    // Vote added/changed
                    if (container.classList.contains('list-group-item') && container.dataset.voteId) {
                        // In voted-subtitles page
                        container.style.opacity = '1';
                        container.dataset.removed = 'false';
                    }
                    container.dataset.currentVote = newVote;
                    
                    if (newVote === 1) {
                        upBtn.className = 'btn btn-sm vote-btn btn-success';
                        downBtn.className = 'btn btn-sm vote-btn btn-outline-danger';
                    } else {
                        upBtn.className = 'btn btn-sm vote-btn btn-outline-success';
                        downBtn.className = 'btn btn-sm vote-btn btn-danger';
                    }
                    
                    if (currentVote === 0) {
                        showToast('Vote recorded.', 'success');
                    } else {
                        showToast('Vote updated.', 'success');
                    }
                }
            }).catch(error => {
                console.error('Error:', error);
                showToast('Error processing vote.', 'danger');
            });
        });
    });
}

