let chatImage = null;
let chatImagePreviewUrl = null;

function clearChatImage() {
    chatImage = null;
    if (chatImagePreviewUrl) URL.revokeObjectURL(chatImagePreviewUrl);
    chatImagePreviewUrl = null;
    document.getElementById('imageAttachment').hidden = true;
    document.getElementById('imageAttachmentPreview').removeAttribute('src');
    document.getElementById('chatImageInput').value = '';
}

function attachChatImage(file) {
    if (!file || document.getElementById('sendBtn').disabled) return;
    if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type)) {
        showToast('Choose a PNG, JPEG or WebP screenshot or photo.', 'warning');
        return;
    }
    if (!file.size || file.size > 8 * 1024 * 1024) {
        showToast('Choose an image smaller than 8 MB.', 'warning');
        return;
    }
    clearChatImage();
    chatImage = file;
    chatImagePreviewUrl = URL.createObjectURL(file);
    document.getElementById('imageAttachmentPreview').src = chatImagePreviewUrl;
    document.getElementById('imageAttachmentName').textContent = file.name;
    document.getElementById('imageAttachment').hidden = false;
    document.getElementById('questionInput').focus();
}

function addChatImagePreview(file) {
    const container = document.getElementById('chatMessages');
    const preview = document.createElement('div');
    preview.className = 'chat-image-message';
    const image = document.createElement('img');
    const url = URL.createObjectURL(file);
    image.alt = 'Screenshot or photo attached to the preceding message';
    image.onload = image.onerror = () => URL.revokeObjectURL(url);
    image.src = url;
    preview.append(image);
    container.append(preview);
    container.scrollTop = container.scrollHeight;
}

// Clipboard images use the same validation and preview as file uploads.
document.getElementById('questionInput').addEventListener('paste', event => {
    const item = [...(event.clipboardData?.items || [])].find(item => item.type.startsWith('image/'));
    if (item) {
        event.preventDefault();
        attachChatImage(item.getAsFile());
    }
});
