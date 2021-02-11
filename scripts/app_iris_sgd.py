import torch
import torch.nn as nn
import torch.nn.functional as F
from sklearn.datasets import load_iris
from torch.utils.data import random_split, DataLoader, TensorDataset

from opendp.smartnoise.network.optimizer import PrivacyAccountant


iris_sklearn = load_iris(as_frame=True)
data = iris_sklearn['data']
target = iris_sklearn['target']

# predictors = ['petal length (cm)', 'petal width (cm)']
predictors = data.columns.values
input_columns = torch.from_numpy(data[predictors].to_numpy()).type(torch.float32)
output_columns = torch.tensor(target)

data = TensorDataset(input_columns, output_columns)

rows = input_columns.shape[0]
test_split = int(rows * .2)
train_split = rows - test_split

train_set, test_set = random_split(data, [train_split, test_split])

train_loader = DataLoader(train_set, batch_size=16, shuffle=True)
test_loader = DataLoader(test_set, batch_size=1)


class IrisModule(nn.Module):
    def __init__(self, input_size, output_size):
        super().__init__()
        internal_size = 5
        self.linear1 = nn.Linear(input_size, internal_size)
        self.linear2 = nn.Linear(internal_size, output_size)

    def forward(self, x):
        x = self.linear1(x)
        x = F.relu(x)
        x = self.linear2(x)
        return x

    def loss(self, batch):
        inputs, targets = batch
        outputs = self(inputs)
        return F.cross_entropy(outputs, targets)

    def score(self, batch):
        with torch.no_grad():
            inputs, targets = batch
            outputs = self(inputs)
            loss = F.cross_entropy(outputs, targets)
            pred = torch.argmax(outputs, dim=1)
            accuracy = torch.sum(pred == targets) / len(pred)
            return [accuracy, loss]


def evaluate(model, loader):
    """Compute average of scores on each batch (unweighted by batch size)"""
    return torch.mean(torch.tensor([model.score(batch) for batch in loader]), dim=0)


model = IrisModule(len(predictors), 3)


# TRAINING
learning_rate = .01
epochs = 16

optimizer = torch.optim.Adam(model.parameters(), learning_rate)

print("Epoch | Accuracy | Loss")

accountant = PrivacyAccountant(model, epoch_epsilon=1.0, epoch_delta=.000001)

for epoch in range(epochs):
    with accountant:
        for batch in train_loader:
            loss = model.loss(batch)
            loss.backward()

            for layer in model.modules():
                accountant.privatize_grad(layer, clipping_norm=1.0, reduction='mean')

            optimizer.step()
            optimizer.zero_grad()
            # for name, param in model.named_parameters():
            #     print(name, param.grad1.size())
            # print("epoch activations: ", epoch)
            # print(activations)

        accuracy, loss = evaluate(model, test_loader)
        print(f"{epoch: 5d} | {accuracy.item():.2f}     | {loss.item():.2f}")


# optimizer = torch.optim.Adam(model.parameters(), learning_rate)
# engine = PrivacyEngine()
# engine.attach(optimizer)
#
# print("Epoch | Accuracy | Loss")
#
# for epoch in range(epochs):
#     for batch in train_loader:
#         loss = model.loss(batch)
#         loss.backward()
#         for param in model.parameters():
#             accountant.privatize_grad(param, 'mean')
#
#         optimizer.step()
#         optimizer.zero_grad()
#         # for name, param in model.named_parameters():
#         #     print(name, param.grad1.size())
#         # print("epoch activations: ", epoch)
#         # print(activations)
#
#     accuracy, loss = evaluate(model, test_loader)
#     print(f"{epoch: 5d} | {accuracy.item():.2f}     | {loss.item():.2f}")
