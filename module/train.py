import time, math, json, torch
import torch.nn as nn
import torch.optim as optim



class Trainer:
    def __init__(self, config, model, train_dataloader, valid_dataloader):
        super(Trainer, self).__init__()
        
        self.model = model
        self.clip = config.clip
        self.device = config.device
        
        self.strategy = config.strategy
        self.n_epochs = config.n_epochs
        self.output_dim = config.output_dim
        
        self.train_dataloader = train_dataloader
        self.valid_dataloader = valid_dataloader

        self.optimizer = optim.AdamW(self.model.parameters(), lr=config.learning_rate)
        self.scheduler = optim.lr_scheduler.ReduceLROnPlateau(self.optimizer, 'min')
        
        self.ckpt_path = config.ckpt_path
        self.record_path = f"ckpt/{self.model_name}.json"
        self.record_keys = ['epoch', 'train_loss', 'train_ppl',
                            'valid_loss', 'valid_ppl', 
                            'learning_rate', 'train_time']


    def print_epoch(self, record_dict):
        print(f"""Epoch {record_dict['epoch']}/{self.n_epochs} | \
              Time: {record_dict['train_time']}""".replace(' ' * 14, ''))
        
        print(f"""  >> Train Loss: {record_dict['train_loss']:.3f} | \
              Train PPL: {record_dict['train_ppl']:.2f}""".replace(' ' * 14, ''))

        print(f"""  >> Valid Loss: {record_dict['valid_loss']:.3f} | \
              Valid PPL: {record_dict['valid_ppl']:.2f}\n""".replace(' ' * 14, ''))


    @staticmethod
    def measure_time(start_time, end_time):
        elapsed_time = end_time - start_time
        elapsed_min = int(elapsed_time / 60)
        elapsed_sec = int(elapsed_time - (elapsed_min * 60))
        return f"{elapsed_min}m {elapsed_sec}s"


    def train(self):
        best_loss, records = float('inf'), []
        for epoch in range(1, self.n_epochs + 1):
            start_time = time.time()

            record_vals = [epoch, *self.train_epoch(), *self.valid_epoch(), 
                           self.optimizer.param_groups[0]['lr'],
                           self.measure_time(start_time, time.time())]
            record_dict = {k: v for k, v in zip(self.record_keys, record_vals)}
            
            records.append(record_dict)
            self.print_epoch(record_dict)
            
            val_loss = record_dict['valid_loss']
            self.scheduler.step(val_loss)

            #save best model
            if best_loss > val_loss:
                best_loss = val_loss
                torch.save({'epoch': epoch,
                            'model_state_dict': self.model.state_dict(),
                            'optimizer_state_dict': self.optimizer.state_dict()},
                            self.ckpt_path)
            
        #save train_records
        with open(self.record_path, 'w') as fp:
            json.dump(records, fp)


    def get_loss(self, batch):
        if self.strategy == 'fine':
            input_ids = batch['input_ids'].to(self.devive)
            token_type_ids = batch['token_type_ids'].to(self.devive)
            attention_mask = batch['attention_mask'].to(self.devive)
            labels = batch['labels'].to(self.devive)
            
            loss = self.model(input_ids=input_ids, token_type_ids=token_type_ids,
                              attention_mask=attention_mask, labels=labels).loss

        elif self.strategy == 'feat':
            sent_embs = batch['sent_embs'].to(self.device)
            sent_masks = batch['sent_masks'].to(self.device)
            labels = batch['labels'].to(self.device)

            loss = self.model(sent_embs=sent_embs, sents_mask=sent_masks, labels=labels).loss            

        return ross


    def train_epoch(self):
        self.model.train()
        epoch_loss = 0
        tot_len = len(self.train_dataloader)

        for idx, batch in enumerate(self.train_dataloader):
            loss = self.get_loss(batch)
            loss.backward()
            nn.utils.clip_grad_norm_(self.model.parameters(), max_norm=self.clip)
            
            self.optimizer.step()
            self.optimizer.zero_grad()

            epoch_loss += loss.item()
        
        epoch_loss = round(epoch_loss / tot_len, 3)
        epoch_ppl = round(math.exp(epoch_loss), 3)    
        return epoch_loss, epoch_ppl
        
    

    def valid_epoch(self):
        self.model.eval()
        epoch_loss = 0
        tot_len = len(self.valid_dataloader)
        
        with torch.no_grad():
            for idx, batch in enumerate(self.valid_dataloader):                
                loss = self.get_loss(batch)
                epoch_loss += loss.item()
        
        epoch_loss = round(epoch_loss / tot_len, 3)
        epoch_ppl = round(math.exp(epoch_loss), 3)        
        return epoch_loss, epoch_ppl