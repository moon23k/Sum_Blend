import torch
import torch.nn as nn
from collections import namedtuple
from transformers import BertModel





class PositionalEncoding(nn.Module):
	def __init__(self, config):
		super(PositionalEncoding, self).__init__()

	def forward(self, x):
		return




class Encoder(nn.Module):
    def __init__(self, config):
        super(Encoder, self).__init__()

        self.layers = nn.TransformerEncoderLayer(d_model=config.hidden_dim, 
        										nhead=config.n_heads,
        										dim_feedforward=config.pff_dim,
        										dropout=config.dropout_ratio,
        										batch_first=config.batch_first,
        										norm_first=config.norm_first,
        										activation=config.act,
        										device=config.device)

    def forward(self, sent_embs, sent_masks):
        x, mask = sent_embs, sent_masks
        for layer in self.layers:
            x = layer(x, mask)
        return x



class Decoder(nn.Module):
    def __init__(self, config):
        super(Decoder, self).__init__()

        self.bert_emb = BertModel.from_pretrained(config.bert_name).embeddings
        self.emb_linear = nn.Linear(config.bert_dim, config.hidden_dim)
        self.emb_dropout = nn.Dropout(config.dropout_ratio)

        self.layers = nn.TransformerEncoderLayer(d_model=config.hidden_dim, 
        	  									 nhead=config.n_heads,
        										 dim_feedforward=config.pff_dim,
        										 dropout=config.dropout_ratio,
        										 batch_first=config.batch_first,
        										 norm_first=config.norm_first,
        										 activation=config.act,
        										 device=config.device)
        

    def forward(self, x, memory, e_mask, d_mask):
        x = self.bert_emb(x)
        x = self.emb_dropout(self.emb_linear(x))

        for layer in self.layers:
            x = layer(x, memory, e_mask, d_mask)
        return x



class FusedModel(nn.Module):
    def __init__(self, config):
        super(FusedModel, self).__init__()
        
        self.device = config.device
        self.pad_id = config.pad_id
        self.max_len = config.max_len
        self.vocab_size = config.vocab_size

		self.sent_pos_encoding = PositionalEncoding(config)

        self.encoder = Encoder(config)
        self.decoder = Decoder(config)
        self.generator = nn.Linear(config.hidden_dim, config.vocab_size)

        self.criterion = nn.CrossEntropyLoss(ignore_index=config.pad_id, 
                                             label_smoothing=0.1).to(self.device)
        self.outputs = namedtuple('outputs', ('logits', 'loss'))


    def pad_mask(self, x):
        return (x != self.pad_id).unsqueeze(1).unsqueeze(2)


    def dec_mask(self, x):
        seq_len = x.size(-1)
        attn_shape = (1, seq_len, seq_len)
        subsequent_mask = torch.triu(torch.ones(attn_shape), diagonal=1).type(torch.uint8) == 0
        return self.pad_mask(x) & subsequent_mask.to(self.device)


    def shift_right(self, labels):
        shifted = labels.new_zeros(labels.size(0), labels.size(1)-1)
        shifted = labels[:, :-1].clone()
        #shifted[:, 0] = self.pad_id #or self.decoder_start_token_id
        return shifted



    def forward(self, sent_embs, sent_masks, labels):
    	sent_embs += self.sent_pos_encoding(sent_embs)

        shifted_labels = self.shift_right(labels)
        label_masks = self.dec_mask(shifted_labels)
        
        memory = self.encoder(sent_embs, sent_masks)
        dec_out = self.decoder(shifted_labels, memory, sent_masks, label_masks)
        
        logits = self.generator(dec_out)
        loss = self.criterion(logits.view(-1, self.vocab_size), 
                              labels[:, 1:].contiguous().view(-1))

        return self.outputs(logits, loss)





class VanillaTransformer(nn.Module):
    def __init__(self, config):
        super(VanillaTransformer, self).__init__()
        
        self.pad_id = config.pad_id
        self.device = config.device
        self.vocab_size = config.vocab_size

        self.embeddings = BertModel.from_pretrained(config.bert_name).embeddings

        self.sent_pos = PositionalEncoding(config)
        self.dec_emb = Embeddings(config)
        
        self.transformer = nn.Transformer(d_model=config.hidden_dim,
                                          nhead=config.n_heads,
                                          dim_feedforward=config.pff_dim,
                                          num_encoder_layers=config.n_layers,
                                          num_decoder_layers=config.n_layers,
                                          dropout=config.dropout_ratio,
                                          batch_first=True,
                                          norm_first=True)

        self.generator = nn.Linear(config.hidden_dim, config.vocab_size)
        self.criterion = nn.CrossEntropyLoss()
        self.out = namedtuple('Out', 'logit loss')

        
    def forward(self, src, trg, label):
        src_pad_mask = (src == self.pad_id).to(self.device)
        trg_pad_mask = (trg == self.pad_id).to(self.device)
        trg_mask = generate_square_subsequent_mask(trg.size(1)).to(self.device)

        src_emb = self.enc_emb(src)
        trg_emb = self.dec_emb(trg)

        memory = self.encode(src_emb, src_pad_mask)
        dec_out = self.decode(trg_emb, memory, trg_mask, trg_pad_mask, src_pad_mask)
        logit = self.generator(dec_out)
        
        loss = self.criterion(logit.contiguous().view(-1, self.vocab_size), 
                              label.contiguous().view(-1))
        
        return self.out(logit, loss)


    def encode(self, src_emb, src_pad_mask):
        return self.transformer.encoder(src_emb, src_key_padding_mask=src_pad_mask)


    def decode(self, trg_emb, memory, trg_mask, trg_pad_mask, src_pad_mask):
        return self.transformer.decoder(trg_emb, memory, tgt_mask=trg_mask,
                                        tgt_key_padding_mask=trg_pad_mask,
                                        memory_key_padding_mask=src_pad_mask)