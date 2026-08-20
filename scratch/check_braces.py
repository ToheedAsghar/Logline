with open("tracker-app/UI/EnrollmentView.swift") as f:
    text = f.read()

count = 0
for i, char in enumerate(text):
    if char == '{': count += 1
    elif char == '}': count -= 1
    if count < 0:
        print(f"Extra closing brace at char {i}")
        break
print(f"Final brace count: {count}")
