document.addEventListener('DOMContentLoaded', function () {
	const uploadInput = document.getElementById('upload');
	const previewImage = document.getElementById('preview-image');
	if (uploadInput && previewImage) {
		const defaultSource = previewImage.getAttribute('src');
		uploadInput.addEventListener('change', function () {
			const file = this.files && this.files[0];
			if (!file) {
				previewImage.src = defaultSource;
				return;
			}

			if (!file.type.startsWith('image/')) {
				return;
			}

			const objectUrl = URL.createObjectURL(file);
			previewImage.src = objectUrl;
			previewImage.onload = function () {
				URL.revokeObjectURL(objectUrl);
			};
		});
	}

	const ingredientList = document.getElementById('ingredient-list');
	const addForm = document.getElementById('add-ingredient-form');
	const addInput = document.getElementById('new-ingredient');
	const emptyState = ingredientList && ingredientList.querySelector('.ingredient-empty');
	const feedback = document.getElementById('ingredient-feedback');
	if (!ingredientList || !addForm || !addInput || !emptyState) return;

	function showFeedback(message) {
		if (feedback) feedback.textContent = message;
	}

	function makeIcon(className) {
		const icon = document.createElement('i');
		icon.className = className;
		icon.setAttribute('aria-hidden', 'true');
		return icon;
	}

	function makeAction(action, iconClass, label) {
		const button = document.createElement('button');
		button.type = 'button';
		button.className = 'ingredient-action';
		button.dataset.action = action;
		button.setAttribute('aria-label', label);
		button.title = label;
		button.append(makeIcon(iconClass));
		return button;
	}

	function makeIngredientCard(name) {
		const card = document.createElement('article');
		card.className = 'ingredient-card';

		const thumb = document.createElement('span');
		thumb.className = 'thumb';
		thumb.setAttribute('aria-hidden', 'true');

		const details = document.createElement('div');
		details.className = 'ingredient-details';
		const nameLabel = document.createElement('span');
		nameLabel.className = 'ingredient-name';
		nameLabel.textContent = name;
		details.append(nameLabel);

		const actions = document.createElement('div');
		actions.className = 'ingredient-actions';
		const editButton = makeAction('edit', 'bi bi-pencil', `Sửa ${name}`);
		editButton.classList.add('edit-ingredient');
		const deleteButton = makeAction('delete', 'bi bi-trash3', `Xóa ${name}`);
		deleteButton.classList.add('delete-ingredient');
		actions.append(editButton, deleteButton);

		card.append(thumb, details, actions);
		return card;
	}

	function updateEmptyState() {
		emptyState.hidden = ingredientList.querySelector('.ingredient-card') !== null;
	}

	function finishEditing(card, newName) {
		const input = card.querySelector('.ingredient-name-input');
		const editButton = card.querySelector('.edit-ingredient');
		if (!input || !editButton) return;

		const nameLabel = document.createElement('span');
		nameLabel.className = 'ingredient-name';
		nameLabel.textContent = newName;
		input.replaceWith(nameLabel);
		card.querySelector('.cancel-edit')?.remove();
		editButton.dataset.action = 'edit';
		editButton.setAttribute('aria-label', `Sửa ${newName}`);
		editButton.title = 'Sửa nguyên liệu';
		editButton.replaceChildren(makeIcon('bi bi-pencil'));
		delete card.dataset.previousName;
	}

	function startEditing(card) {
		const nameLabel = card.querySelector('.ingredient-name');
		const editButton = card.querySelector('.edit-ingredient');
		if (!nameLabel || !editButton) return;

		const originalName = nameLabel.textContent || '';
		card.dataset.previousName = originalName;
		const input = document.createElement('input');
		input.className = 'ingredient-name-input';
		input.type = 'text';
		input.value = originalName;
		input.maxLength = 80;
		input.required = true;
		input.setAttribute('aria-label', `Tên nguyên liệu: ${originalName}`);
		nameLabel.replaceWith(input);

		editButton.dataset.action = 'save';
		editButton.setAttribute('aria-label', 'Lưu thay đổi');
		editButton.title = 'Lưu thay đổi';
		editButton.replaceChildren(makeIcon('bi bi-check-lg'));
		const cancelButton = makeAction('cancel', 'bi bi-x-lg', 'Hủy sửa');
		cancelButton.classList.add('cancel-edit');
		card.querySelector('.ingredient-actions').append(cancelButton);
		input.focus();
		input.select();
	}

	function saveEditing(card) {
		const input = card.querySelector('.ingredient-name-input');
		if (!input) return;

		const name = input.value.trim();
		if (!name) {
			input.setCustomValidity('Vui lòng nhập tên nguyên liệu.');
			input.reportValidity();
			return;
		}

		finishEditing(card, name);
		showFeedback(`Đã cập nhật nguyên liệu thành "${name}".`);
	}

	addForm.addEventListener('submit', function (event) {
		event.preventDefault();
		const name = addInput.value.trim();
		if (!name) {
			addInput.setCustomValidity('Vui lòng nhập tên nguyên liệu.');
			addInput.reportValidity();
			return;
		}

		ingredientList.insertBefore(makeIngredientCard(name), emptyState);
		addForm.reset();
		showFeedback(`Đã thêm nguyên liệu "${name}".`);
		updateEmptyState();
		addInput.focus();
	});

	addInput.addEventListener('input', function () {
		addInput.setCustomValidity('');
	});

	ingredientList.addEventListener('click', function (event) {
		const button = event.target.closest('button[data-action]');
		if (!button || !ingredientList.contains(button)) return;

		const card = button.closest('.ingredient-card');
		if (!card) return;

		if (button.dataset.action === 'edit') {
			startEditing(card);
		} else if (button.dataset.action === 'save') {
			saveEditing(card);
		} else if (button.dataset.action === 'cancel') {
			finishEditing(card, card.dataset.previousName || '');
		} else if (button.dataset.action === 'delete') {
			const name = card.querySelector('.ingredient-name')?.textContent || 'nguyên liệu';
			card.remove();
			showFeedback(`Đã xóa nguyên liệu "${name}".`);
			updateEmptyState();
		}
	});

	ingredientList.addEventListener('input', function (event) {
		if (event.target.matches('.ingredient-name-input')) {
			event.target.setCustomValidity('');
		}
	});

	ingredientList.addEventListener('keydown', function (event) {
		if (!event.target.matches('.ingredient-name-input')) return;
		const card = event.target.closest('.ingredient-card');
		if (!card) return;

		if (event.key === 'Enter') {
			event.preventDefault();
			saveEditing(card);
		} else if (event.key === 'Escape') {
			finishEditing(card, card.dataset.previousName || '');
		}
	});

	updateEmptyState();
});
